#include "esp_log.h"
#include "esp_mac.h"
#include "esp_wifi.h"

#include "../_components/csi_component.h"
#include "../_components/nvs_component.h"
#include "../_components/time_component.h"

#define ESP_WIFI_SSID   CONFIG_ESP_WIFI_SSID
#define ESP_WIFI_PASS   CONFIG_ESP_WIFI_PASSWORD
#define WIFI_CHANNEL    CONFIG_ESP_WIFI_CHANNEL
#define MAX_STA_CONN    CONFIG_ESP_MAX_STA_CONN

const char *MAIN = "Main";

static void wifi_event_handler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data) {
    if (event_id == WIFI_EVENT_AP_STACONNECTED) {
        wifi_event_ap_staconnected_t* event = (wifi_event_ap_staconnected_t*) event_data;
        ESP_LOGI(MAIN, "station " MACSTR " join, AID=%d",
                 MAC2STR(event->mac), event->aid);
    } else if (event_id == WIFI_EVENT_AP_STADISCONNECTED) {
        wifi_event_ap_stadisconnected_t* event = (wifi_event_ap_stadisconnected_t*) event_data;
        ESP_LOGI(MAIN, "station " MACSTR " leave, AID=%d", MAC2STR(event->mac), event->aid);
    }
}

void config_print() {
    printf("\n\n");
    printf("-----------------------\n");
    printf("ESP32 CSI Tool Settings\n");
    printf("-----------------------\n");
    printf("PROJECT_NAME: %s\n", "WiReMap");
    printf("CONFIG_ESPTOOLPY_MONITOR_BAUD: %d\n", CONFIG_ESPTOOLPY_MONITOR_BAUD);
    printf("CONFIG_ESP_CONSOLE_UART_BAUDRATE: %d\n", CONFIG_ESP_CONSOLE_UART_BAUDRATE);
    printf("-----------------------\n");
    printf("WIFI_CHANNEL: %d\n", WIFI_CHANNEL);
    printf("ESP_WIFI_SSID: %s\n", ESP_WIFI_SSID);
    printf("ESP_WIFI_PASSWORD: %s\n", ESP_WIFI_PASS);
    printf("-----------------------\n");
    printf("\n\n");
}

void wifi_init_softap() {
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL));

    wifi_ap_config_t wifi_ap_config = {};
    wifi_ap_config.channel = WIFI_CHANNEL;
    wifi_ap_config.authmode = WIFI_AUTH_WPA_WPA2_PSK;
    wifi_ap_config.max_connection = MAX_STA_CONN;

    wifi_config_t wifi_config = {
            .ap = wifi_ap_config,
    };

    strlcpy((char *) wifi_config.ap.ssid, ESP_WIFI_SSID, sizeof(ESP_WIFI_SSID));
    strlcpy((char *) wifi_config.ap.password, ESP_WIFI_PASS, sizeof(ESP_WIFI_PASS));

    if (strlen(ESP_WIFI_PASS) == 0) {
        wifi_config.ap.authmode = WIFI_AUTH_OPEN;
    }

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(MAIN, "wifi_init_softap finished. SSID:%s password:%s channel:%d",
             ESP_WIFI_SSID, ESP_WIFI_PASS, WIFI_CHANNEL);
}

extern "C" void app_main() {
    config_print();
    nvs_init();
    wifi_init_softap();
    csi_init((char *) "CSI_AP");
}