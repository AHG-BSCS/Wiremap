import os
import re
import csv
import math
import numpy as np
import pandas as pd
import socket
import subprocess
import time
import threading
from scapy.all import Raw, IP, UDP, datetime, send
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__)
lock = threading.Lock()

SSID = 'Wiremap'
PASSWORD = 'WiReMap@ESP32'
ESP32_IP = '192.168.4.1' # Default IP address of the ESP32 AP
PAYLOAD = 'Wiremap' # Signal Length is 89
ESP32_PORT = 5001

recording = False
total_packet_count = 0
packet_count = 0
max_packets = 25
packet_interval = 0.1

csv_file_path = None
sending_timestamp = []
COLUMN_NAMES = [
    'Sending_Timestamp', 'Recording_Timestamp', 'Type', 'Mode', 'Source_IP', 'RSSI', 'Rate', 'Sig_Mode', 'MCS', 'CWB', 'Smoothing', 
    'Not_Sounding', 'Aggregation', 'STBC', 'FEC_Coding', 'SGI', 'Noise_Floor', 'AMPDU_Cnt', 
    'Channel', 'Secondary_Channel', 'Received_Timestamp', 'Antenna', 'Signal_Length', 'RX_State', 
    'Real_Time_Set', 'Steady_Clock_Timestamp', 'Data_Length', 'Raw_CSI', 'Amplitude', 'Phase', 'Time_of_Flight'
]

def filter_reflections(amplitudes, phases, amplitude_threshold=10):
    """
    Filters out the direct path data based on amplitude threshold.
    """
    filtered_amplitudes = []
    filtered_phases = []
    
    for amp, phase in zip(amplitudes, phases):
        amp = np.array(amp)
        phase = np.array(phase)
        
        # Filter values below the amplitude threshold
        mask = amp < amplitude_threshold
        filtered_amplitudes.append(amp[mask])
        filtered_phases.append(phase[mask])
    
    return filtered_amplitudes, filtered_phases

def map_reflections_to_3d(filtered_amplitudes, filtered_phases):
    """
    Maps reflected CSI data to approximate 3D coordinates.
    """
    reflected_positions = []
    for amp, phase in zip(filtered_amplitudes, filtered_phases):
        # Use amplitude to approximate distance (scaled)
        distances = amp / np.max(amp) * 10  # Normalize and scale distances
        angles = np.linspace(0, 2 * np.pi, len(amp))  # Spread reflections in a circular pattern
        
        # Map to 3D coordinates
        x = distances * np.cos(angles)
        y = distances * np.sin(angles)
        z = phase  # Use phase as an approximation for height variation
        
        for i in range(len(x)):
            reflected_positions.append((x[i], y[i], z[i]))
            # reflected_positions.append((float(x[i]), float(y[i]), float(z[i])))
    
    return reflected_positions

def compute_csi_amplitude_phase(csi_data):
    '''
    Compute amplitude and phase from raw CSI data.
    param csi_data: List of raw CSI values (alternating I and Q components).
    return: Two lists - amplitudes and phases for each subcarrier.
    '''
    amplitudes = []
    phases = []
    
    # Ensure the data length is even (pairs of I and Q)
    if len(csi_data) % 2 != 0:
        raise ValueError('CSI data length must be even (pairs of I and Q values).')
    
    for i in range(0, len(csi_data), 2):
        I = csi_data[i]
        Q = csi_data[i + 1]
        
        amplitude = math.sqrt(I**2 + Q**2)
        phase = math.atan2(Q, I)  # atan2 handles quadrant ambiguity
        
        amplitudes.append(amplitude)
        phases.append(phase)
    
    return amplitudes, phases

def parse_csi_data(data_str):
    parts = data_str.split(',')
    csi_data_start = data_str.find('[')
    csi_data_end = data_str.find(']')

    # Extract CSI data as a string of integers
    csi_data = data_str[csi_data_start + 1:csi_data_end].strip().split(' ')
    csi_data = list(filter(None, csi_data))  # Remove empty strings

    try:
        csi_data = [int(x) for x in csi_data]
        amplitudes, phases = compute_csi_amplitude_phase(csi_data)
    except ValueError:
        csi_data, amplitudes, phases = [], [], []

    return parts[:25] + [csi_data, amplitudes, phases]

def compute_time_of_flight(previous_row, current_row):
    print(f"Previous system time: {previous_row}")
    print(f"Current system time: {current_row}")

    time_of_flight_microseconds = current_row - previous_row
    time_of_flight_seconds = time_of_flight_microseconds / 1_000_000
    return time_of_flight_seconds

def process_data(data, received_time):
    try:
        data_str = data.decode('utf-8').strip()
        csi_data = parse_csi_data(data_str)
        csi_data.insert(0, sending_timestamp.pop(0))
        csi_data.insert(1, received_time)

        # previous_row = int(csi_data[:][20])
        # current_row = int(csi_data[:][20])
        # print(type(csi_data))
        # tof = compute_time_of_flight(previous_row, current_row)
        # csi_data.insert(30, tof)
            
        # Write to the CSV file with a lock to ensure thread safety
        with lock:
            with open(csv_file_path, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(csi_data)
    except Exception as e:
        print(f'Error processing data: {e}')
    
    # if not recording:
    #     csi_df = pd.read_csv(csv_file_path)
    #     recording_time = csi_df['Recording_Timestamp']
    #     received_time = csi_df['Received_Timestamp']



def listen_to_packets():
    global recording, packet_count
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    client.bind(('0.0.0.0', 5000))
    client.settimeout(1.0)

    print('Recording CSI data...')
    while recording:
        try:
            data, addr = client.recvfrom(2048) # Adjusted buffer size for CSI Data
            received_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            packet_count += 1

            if total_packet_count + packet_count <= max_packets:
                threading.Thread(target=process_data, args=(data, received_time)).start()
            else:
                break
        except socket.timeout:
            if not recording:
                break
            continue
        except KeyboardInterrupt:
            break

    recording = False   
    print('Stopped recording CSI data.')

def send_packets():
    global recording
    udp_packet = IP(dst=ESP32_IP)/UDP(sport=5000, dport=ESP32_PORT)/Raw(load=PAYLOAD)

    try:
        while recording and total_packet_count + packet_count <= max_packets:
            send(udp_packet)
            sending_timestamp.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'))
            time.sleep(packet_interval)
    except KeyboardInterrupt:
        recording = False
        print('Stopped sending packets.')

def packet_counter():
    global total_packet_count, packet_count
    total_packet_count += packet_count

    if (recording):
        print('Packets received in 1s:', packet_count)
        print('Total packets received:', total_packet_count)
        packet_count = 0 # Reset the packet counter
        threading.Timer(1.0, packet_counter).start()
    else:
        time.sleep(1.0)
        total_packet_count = 0
        packet_count = 0

def prepare_csv_file():
    global csv_file_path
    csv_dir = 'app/dataset'
    files = os.listdir(csv_dir)
    
    # Filter files that match the pattern CSI_DATA_XXX
    pattern = re.compile(r'^CSI_DATA_.*$')
    matching_files = [f for f in files if pattern.match(f)]
    
    # Extract the numeric part and find the highest number
    if matching_files:
        numbers = [int(f[9:12]) for f in matching_files if f[9:12].isdigit()]
        next_number = max(numbers) + 1
    else:
        next_number = 1
    
    csv_file_path = os.path.join(csv_dir, f'CSI_DATA_{next_number:03d}.csv')

    try:
        with open(csv_file_path, mode='x', newline='') as file:  # 'x' ensures the file is created and not overwritten
            writer = csv.writer(file)
            writer.writerow(COLUMN_NAMES)
    except FileExistsError:
        pass

def check_connection(ssid):
    result = subprocess.run(['netsh', 'wlan', 'show', 'interfaces'], capture_output=True, text=True, shell=True)
    return ssid in result.stdout


@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/start_recording', methods=['POST'])
def start_recording():
    global recording
    recording = True

    prepare_csv_file()
    packet_counter()
    threading.Thread(target=listen_to_packets, daemon=True).start()
    time.sleep(0.9)  # Wait for listerning thread to start
    threading.Thread(target=send_packets, daemon=True).start()
    return 'Start recording CSI Data.'

@app.route('/recording_status', methods=['POST'])
def recording_status():
    return jsonify({
        'status': recording,
        'total_packet_count': total_packet_count,
    })

@app.route('/stop_recording', methods=['POST'])
def stop_recording():
    global recording
    recording = False
    return 'Stop recording CSI Data.'

@app.route('/visualize', methods=['POST'])
def visualize():
    if not os.path.exists(csv_file_path):
        return jsonify({"error": "No CSV file found"}), 404
    
    try:
        csi_df = pd.read_csv(csv_file_path)
        csi_amplitude = csi_df['CSI_Amplitude'].apply(eval)
        csi_phase = csi_df['CSI_Phase'].apply(eval)

        amplitude_threshold = 10
        filtered_amplitudes, filtered_phases = filter_reflections(csi_amplitude, csi_phase, amplitude_threshold)
        reflected_positions = map_reflections_to_3d(filtered_amplitudes, filtered_phases)
        
        # AP and Device positions (fixed)
        ap_position = {"x": 0, "y": 0, "z": 0}
        device_position = {"x": 5, "y": 0, "z": 0}
        
        return jsonify({
            "ap_position": ap_position,
            "device_position": device_position,
            "reflected_positions": reflected_positions
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/list_csv_files', methods=['GET'])
def list_attendance_files():
    attendance_files = [f for f in os.listdir('app/dataset') if f.endswith('.csv')]
    return jsonify(attendance_files)

@app.route('/visualize_csv/<filename>', methods=['GET'])
def visualize_csv(filename):
    global csv_file_path
    csv_file_path = os.path.join('app/dataset', filename)

    if not os.path.exists(csv_file_path):
        return jsonify({"error": "File not found"}), 404
    return 'CSV file set for visualization.'

if __name__ == '__main__':
    # Check if the device is connected to the ESP32 AP
    # while not check_connection(SSID):
    #     print('Waiting to connect to ESP32 AP')
    #     print('SSID:', SSID)
    #     print('Passord:', PASSWORD, '\n')
    #     time.sleep(5)
    # else:
    #     print(f'Connected to {SSID}. Starting the server...')
    
    app.run(host='0.0.0.0', port=3000, debug=True)
    