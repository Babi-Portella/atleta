// M5StickC Plus2: sensores reais, sessão, estimativas identificadas e MQTT/MySQL.
#include <Arduino.h>
#include <ArduinoJson.h>
#include <M5Unified.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include <esp_timer.h>
#include <atomic>
#include "activity.h"

namespace {
constexpr char VERSION[] = "2.1.7";
constexpr uint32_t IMU_MS = 20, TELEMETRY_MS = 2000;
constexpr size_t MAX_CONFIG = 2048, MAX_PAYLOAD = 2048;
constexpr char BLE_SERVICE[] = "747e1000-7e91-4e27-a560-697562673001";
constexpr char BLE_SUMMARY[] = "747e1001-7e91-4e27-a560-697562673001";
Preferences prefs;
String ssid, wifiPassword, host, user, mqttPassword, deviceId, topic, serialLine;
uint16_t mqttPort = 1883;
float weightKg = 0, stepLengthM = 0, activityMet = 0;
uint32_t athleteId = 0;
char bootId[17], sessionId[32];
uint32_t sequence = 0, sessionNumber = 0, lastImu = 0, lastGoodImu = 0, lastTelemetry = 0, lastDisplay = 0;
uint64_t activeMs = 0, lastTick = 0;
bool running = true, discardLine = false, imuHealthy = false;
float ax = 0, ay = 0, az = 0, gx = 0, gy = 0, gz = 0;
int batteryMv = 0, batteryPercent = -1, page = 0;
StepCounter steps;
bool imuTrace = false;
bool imuTraceMqtt = false;
uint32_t traceStarted = 0, traceSamples = 0, traceDropped = 0;
// Dá tempo de retirar o USB, colocar no pulso e concluir os testes por Wi-Fi.
constexpr uint32_t MAX_TRACE_MS = 600000;
struct TraceSample {
  uint32_t ms, cadence, pending, count;
  float accel[3], gyro[3], filtered;
  uint8_t event, active;
};
TraceSample traceBatch[5];
size_t traceBatchSize = 0;
struct Message { char payload[MAX_PAYLOAD]; };
QueueHandle_t outgoing = nullptr;
std::atomic<bool> mqttOnline{false};
std::atomic<int> mqttError{-1};
std::atomic<int> wifiReason{0};
std::atomic<bool> scanWifiRequested{false};
std::atomic<uint32_t> sentCount{0};
BLEServer* bleServer = nullptr;
BLECharacteristic* bleCharacteristic = nullptr;
bool bleEnabled = false, bleInitialized = false;
std::atomic<bool> bleConnected{false}, bleRestart{false};

void emitJson(const char* prefix, const JsonDocument& doc) {
  String line;
  serializeJson(doc, line);
  Serial.printf("%s%s\n", prefix, line.c_str());
}

bool validId(const String& id) {
  if (id.isEmpty() || id.length() > 48) return false;
  for (char c : id) if (!isalnum(static_cast<unsigned char>(c)) && c != '-' && c != '_') return false;
  return true;
}

void loadConfig() {
  prefs.begin("atleta-lab", true);
  String saved = prefs.getString("config", "{}");
  prefs.end();
  JsonDocument doc;
  if (deserializeJson(doc, saved)) return;
  ssid = doc["wifi_ssid"] | "";
  wifiPassword = doc["wifi_password"] | "";
  host = doc["mqtt_host"] | "";
  mqttPort = doc["mqtt_port"] | 1883;
  deviceId = doc["device_id"] | "m5-atleta-01";
  user = doc["mqtt_username"] | "m5-atleta-01";
  mqttPassword = doc["mqtt_password"] | "";
  weightKg = doc["weight_kg"] | 0.0f;
  stepLengthM = doc["step_length_m"] | 0.0f;
  activityMet = doc["activity_met"] | 0.0f;
  athleteId = doc["athlete_id"] | 0u;
  topic = "atletas/" + deviceId + "/telemetria";
}

void acceptConfig(const String& json) {
  JsonDocument doc;
  if (deserializeJson(doc, json)) { Serial.println("CONFIG_ERROR json"); return; }
  for (const char* key : {"wifi_ssid", "wifi_password", "mqtt_host", "device_id", "mqtt_username", "mqtt_password"}) {
    if (!doc[key].is<const char*>()) { Serial.println("CONFIG_ERROR fields"); return; }
  }
  String newHost = doc["mqtt_host"].as<String>();
  String newId = doc["device_id"].as<String>();
  int port = doc["mqtt_port"] | 0;
  if (!validId(newId) || newId != doc["mqtt_username"].as<String>() || newHost.isEmpty() ||
      newHost == "localhost" || newHost == "127.0.0.1" || newHost == "0.0.0.0" ||
      newHost.indexOf('/') >= 0 || newHost.indexOf(' ') >= 0 ||
      port < 1 || port > 65535 || doc["wifi_ssid"].as<String>().isEmpty() ||
      doc["wifi_ssid"].as<String>().length() > 32 || doc["wifi_password"].as<String>().length() > 64 ||
      doc["mqtt_password"].as<String>().isEmpty()) {
    Serial.println("CONFIG_ERROR values"); return;
  }
  for (const char* key : {"weight_kg", "step_length_m", "activity_met", "athlete_id"}) {
    if (doc[key].isNull()) continue;
    float value = doc[key].as<float>();
    float lower = String(key) == "weight_kg" ? 10 : String(key) == "step_length_m" ? 0.1f : 1;
    float upper = String(key) == "weight_kg" ? 400 : String(key) == "step_length_m" ? 2.5f : String(key) == "activity_met" ? 25 : 2147483647.0f;
    if (!doc[key].is<float>() || !isfinite(value) || value < lower || value > upper ||
        (String(key) == "athlete_id" && !doc[key].is<uint32_t>())) {
      Serial.println("CONFIG_ERROR profile"); return;
    }
  }
  prefs.begin("atleta-lab", false);
  size_t stored = prefs.putString("config", json);
  prefs.end();
  if (!stored) { Serial.println("CONFIG_ERROR storage"); return; }
  Serial.println("CONFIG_OK");
  Serial.flush(); delay(300); ESP.restart();
}

void networkTask(void*) {
  WiFiClient transport;
  PubSubClient mqtt(transport);
  mqtt.setBufferSize(MAX_PAYLOAD + 256);
  mqtt.setSocketTimeout(2);
  mqtt.setKeepAlive(20);
  WiFi.mode(WIFI_STA);
  WiFi.onEvent([](WiFiEvent_t event, WiFiEventInfo_t info) {
    if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
      wifiReason = info.wifi_sta_disconnected.reason;
      Serial.printf("WIFI_DISCONNECTED reason=%d\n", wifiReason.load());
    }
    if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) { wifiReason = 0; Serial.println("WIFI_CONNECTED"); }
  });
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  bool configured = !ssid.isEmpty() && !host.isEmpty() && !mqttPassword.isEmpty();
  if (configured) WiFi.begin(ssid.c_str(), wifiPassword.c_str());
  uint32_t wifiRetry = millis(), mqttRetry = 0;
  Message message;
  while (true) {
    uint32_t now = millis();
    if (scanWifiRequested.exchange(false)) {
      // A busca falha se a tentativa automática de associação estiver em andamento.
      WiFi.setAutoReconnect(false);
      WiFi.disconnect(false, false);
      vTaskDelay(pdMS_TO_TICKS(300));
      int count = WiFi.scanNetworks(false, false, false, 300);
      JsonDocument scan;
      scan["scan_success"] = count >= 0;
      scan["networks_seen"] = count >= 0 ? count : 0;
      scan["configured_ssid_seen"] = false;
      auto matches = scan["matching_networks"].to<JsonArray>();
      for (int index = 0; index < count; ++index) {
        if (WiFi.SSID(index).equalsIgnoreCase(ssid)) {
          auto found = matches.add<JsonObject>();
          found["exact_name"] = WiFi.SSID(index) == ssid;
          found["ssid"] = WiFi.SSID(index);
          found["channel"] = WiFi.channel(index);
          found["rssi_dbm"] = WiFi.RSSI(index);
          found["auth_mode"] = int(WiFi.encryptionType(index));
          if (WiFi.SSID(index) == ssid) scan["configured_ssid_seen"] = true;
        }
      }
      WiFi.scanDelete();
      emitJson("WIFI_SCAN ", scan);
      WiFi.setAutoReconnect(true);
      if (configured) WiFi.begin(ssid.c_str(), wifiPassword.c_str());
      wifiRetry = millis();
    }
    if (configured && WiFi.status() != WL_CONNECTED && now - wifiRetry >= 15000) {
      wifiRetry = now; WiFi.reconnect();
    }
    if (configured && WiFi.status() == WL_CONNECTED && !mqtt.connected() && now - mqttRetry >= 5000) {
      mqttRetry = now;
      mqtt.setServer(host.c_str(), mqttPort);
      if (mqtt.connect(deviceId.c_str(), user.c_str(), mqttPassword.c_str())) Serial.println("MQTT_CONNECTED");
      else Serial.printf("MQTT_ERROR code=%d\n", mqtt.state());
      mqttError = mqtt.state();
    }
    if (mqtt.connected()) mqtt.loop();
    mqttOnline = mqtt.connected();
    if (outgoing && xQueueReceive(outgoing, &message, 0) == pdTRUE && mqtt.connected()) {
      // QoS 0, fila só da leitura mais recente; confirmação final é a consulta MySQL.
      if (mqtt.publish(topic.c_str(), message.payload, false)) ++sentCount;
      else Serial.println("MQTT_PUBLISH_FAILED");
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

class BleCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer*) override { bleConnected = true; }
  void onDisconnect(BLEServer*) override { bleConnected = false; bleRestart = true; }
};

void setBluetooth(bool enabled) {
  if (enabled && !bleInitialized) {
    BLEDevice::init("Atleta-M5");
    bleServer = BLEDevice::createServer();
    bleServer->setCallbacks(new BleCallbacks());
    auto service = bleServer->createService(BLE_SERVICE);
    bleCharacteristic = service->createCharacteristic(BLE_SUMMARY,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
    bleCharacteristic->addDescriptor(new BLE2902());
    uint8_t initial[16] = {1};
    bleCharacteristic->setValue(initial, sizeof(initial));
    service->start();
    BLEDevice::getAdvertising()->addServiceUUID(BLE_SERVICE);
    BLEDevice::getAdvertising()->setScanResponse(true);
    bleInitialized = true;
  }
  bleEnabled = enabled;
  if (bleInitialized) {
    if (enabled) BLEDevice::startAdvertising();
    else {
      BLEDevice::getAdvertising()->stop();
      if (bleConnected) bleServer->disconnect(bleServer->getConnId());
    }
  }
  Serial.printf("BLE_STATUS enabled=%d connected=%d\n", bleEnabled, bleConnected.load());
}

const char* bluetoothState() {
  return !bleEnabled ? "desligado" : bleConnected ? "conectado" : "anunciando";
}

void inventory(bool scanExternal) {
  JsonDocument doc;
  doc["firmware"] = VERSION;
  doc["board"] = "M5StickCPlus2";
  doc["chip"] = ESP.getChipModel();
  doc["flash_bytes"] = ESP.getFlashChipSize();
  doc["psram_bytes"] = ESP.getPsramSize();
  doc["imu_enabled"] = M5.Imu.isEnabled();
  doc["imu_type"] = static_cast<int>(M5.Imu.getType());
  doc["imu_who_am_i"] = M5.In_I2C.readRegister8(0x68, 0x75, 100000);
  doc["rtc_0x51_responds"] = M5.In_I2C.scanID(uint8_t(0x51));
  doc["external_scan_performed"] = scanExternal;
  auto addresses = doc["external_i2c_addresses"].to<JsonArray>();
  if (scanExternal) {
    // Apenas o barramento Grove documentado: SDA32/SCL33. Nenhum GPIO aleatório.
    doc["external_sda"] = M5.Ex_I2C.getSDA();
    doc["external_scl"] = M5.Ex_I2C.getSCL();
    bool scanned = M5.Ex_I2C.getSDA() == 32 && M5.Ex_I2C.getSCL() == 33 && M5.Ex_I2C.begin();
    doc["external_scan_ok"] = scanned;
    if (scanned) for (uint8_t address = 8; address < 120; ++address) {
      if (M5.Ex_I2C.scanID(address, 100000)) addresses.add(address);
    }
  }
  doc["analog_sensor_identification"] = "requires_model_and_wiring";
  doc["ble_state"] = bluetoothState();
  doc["wifi_status_code"] = int(WiFi.status());
  doc["wifi_disconnect_reason"] = wifiReason.load();
  doc["wifi_ip"] = WiFi.localIP().toString();
  doc["mqtt_host"] = host;
  doc["mqtt_port"] = mqttPort;
  emitJson("INVENTORY ", doc);
}

void startSession() {
  ++sessionNumber; activeMs = 0; steps.reset(); running = true;
  snprintf(sessionId, sizeof(sessionId), "%s-%lu", bootId, static_cast<unsigned long>(sessionNumber));
  Serial.println("SESSION_STARTED");
}

void selfTest() {
  StepCounter stationary, rotating, walking, invalid, interrupted, tooFast, irregular, changing;
  constexpr uint32_t irregularPeaks[] = {500, 1000, 2600, 3100, 4700,
                                          5200, 6800, 7300, 8900, 9400};
  constexpr uint32_t changingPeaks[] = {500, 1000, 1500, 2220, 2720, 3220, 3720, 4220};
  for (uint32_t t = 0; t < 10000; t += 20) {
    float phase = 2 * PI * 2 * t / 1000;
    stationary.add(t, 0, 0, 1);
    rotating.add(t, sinf(phase), 0, cosf(phase));
    walking.add(t, 0, 0, 1 + 0.23f * sinf(phase));
    invalid.add(t, NAN, 0, 1);
    interrupted.add(t * 100, 0, 0, 1 + 0.23f * sinf(phase));
    tooFast.add(t, 0, 0, 1 + 0.23f * sinf(phase * 2));
    float bump = 1;
    for (uint32_t peak : irregularPeaks) {
      float delta = (static_cast<float>(t) - peak) / 65;
      bump += 0.3f * expf(-delta * delta);
    }
    irregular.add(t, 0, 0, bump);
    bump = 1;
    for (uint32_t peak : changingPeaks) {
      float delta = (static_cast<float>(t) - peak) / 65;
      bump += 0.3f * expf(-delta * delta);
    }
    changing.add(t, 0, 0, bump);
  }
  JsonDocument doc;
  doc["stationary_zero"] = stationary.steps == 0;
  doc["rotation_zero"] = rotating.steps == 0;
  doc["invalid_zero"] = invalid.steps == 0;
  doc["gaps_zero"] = interrupted.steps == 0;
  doc["regular_peaks"] = walking.steps >= 18 && walking.steps <= 21;
  doc["irregular_zero"] = irregular.steps == 0;
  doc["double_peaks_limited"] = tooFast.steps <= 23;
  doc["short_walk_variable_cadence"] = changing.steps == 8;
  doc["variable_cadence_steps"] = changing.steps;
  doc["synthetic_steps"] = walking.steps;
  doc["distance_formula"] = fabsf(estimatedDistanceKm(1000, 0.7f) - 0.7f) < 0.0001f;
  doc["calories_formula"] = fabsf(estimatedCalories(3600000, 70, 3.8f) - 266) < 0.001f;
  doc["missing_profile_null"] = isnan(estimatedDistanceKm(100, 0)) && isnan(estimatedCalories(1000, 0, 0));
  emitJson("SELFTEST ", doc);
}

void stopImuTrace() {
  if (!imuTrace) return;
  imuTrace = false;
  Serial.printf("IMU_TRACE_DONE samples=%lu dropped=%lu\n",
      static_cast<unsigned long>(traceSamples), static_cast<unsigned long>(traceDropped));
}

void traceImuSample(uint32_t now) {
  if (!imuTrace) return;
  if (imuTraceMqtt) {
    if (traceBatchSize == 5) { ++traceDropped; return; }
    traceBatch[traceBatchSize++] = {now, steps.cadenceInterval(), steps.pendingPeaks(), steps.steps,
        {ax, ay, az}, {gx, gy, gz}, steps.filteredAcceleration(),
        static_cast<uint8_t>(steps.lastEvent()), static_cast<uint8_t>(running ? 1 : 0)};
    ++traceSamples; return;
  }
  char line[224];
  int length = snprintf(line, sizeof(line),
      "IMU_SAMPLE %lu,%.4f,%.4f,%.4f,%.2f,%.2f,%.2f,%.4f,%lu,%lu,%u,%lu,%u\n",
      static_cast<unsigned long>(now), ax, ay, az, gx, gy, gz,
      steps.filteredAcceleration(), static_cast<unsigned long>(steps.cadenceInterval()),
      static_cast<unsigned long>(steps.pendingPeaks()), static_cast<unsigned>(steps.lastEvent()),
      static_cast<unsigned long>(steps.steps), running ? 1 : 0);
  // Não bloquear a amostragem se o computador parar de ler a USB.
  if (length <= 0 || length >= static_cast<int>(sizeof(line)) || Serial.availableForWrite() < length) {
    ++traceDropped; return;
  }
  Serial.write(reinterpret_cast<const uint8_t*>(line), length);
  ++traceSamples;
}

void readSerial() {
  while (Serial.available()) {
    char c = static_cast<char>(Serial.read());
    if (c == '\r') continue;
    if (c != '\n') {
      if (!discardLine) {
        if (serialLine.length() >= MAX_CONFIG) { serialLine = ""; discardLine = true; Serial.println("CONFIG_ERROR too_long"); }
        else serialLine += c;
      }
      continue;
    }
    if (!discardLine) {
      if (serialLine.startsWith("CONFIG ")) acceptConfig(serialLine.substring(7));
      else if (serialLine == "INVENTORY") inventory(false);
      else if (serialLine == "SCAN_I2C") inventory(true);
      else if (serialLine == "SELFTEST") selfTest();
      else if (serialLine == "TRACE_IMU ON") {
        imuTrace = true; imuTraceMqtt = false; traceBatchSize = 0;
        traceStarted = millis(); traceSamples = 0; traceDropped = 0;
        Serial.printf("IMU_TRACE_BEGIN schema=1 rate_hz=50 timeout_s=%lu start_ms=%lu\n",
            static_cast<unsigned long>(MAX_TRACE_MS / 1000), static_cast<unsigned long>(traceStarted));
      }
      else if (serialLine == "TRACE_MQTT ON") {
        if (WiFi.status() != WL_CONNECTED || !mqttOnline.load()) {
          Serial.println("IMU_TRACE_ERROR wifi_mqtt_offline");
        } else {
          imuTrace = true; imuTraceMqtt = true; traceBatchSize = 0;
          traceStarted = millis(); traceSamples = 0; traceDropped = 0;
          Serial.printf("IMU_TRACE_BEGIN schema=2 transport=mqtt rate_hz=50 timeout_s=%lu start_ms=%lu\n",
              static_cast<unsigned long>(MAX_TRACE_MS / 1000), static_cast<unsigned long>(traceStarted));
        }
      }
      else if (serialLine == "TRACE_IMU OFF") stopImuTrace();
      else if (serialLine == "SCAN_WIFI") scanWifiRequested = true;
      else if (serialLine == "BLE ON") setBluetooth(true);
      else if (serialLine == "BLE OFF") setBluetooth(false);
      else if (serialLine == "SESSION START") startSession();
      else if (serialLine == "SESSION PAUSE") { running = false; steps.breakSequence(); Serial.println("SESSION_PAUSED"); }
      else if (serialLine == "SESSION RESUME") { running = true; steps.breakSequence(); Serial.println("SESSION_RESUMED"); }
      else if (serialLine == "STATUS") Serial.printf("STATUS firmware=%s configured=%d wifi=%d mqtt=%d imu=%d sent=%lu steps=%lu ble=%s\n",
          VERSION, !host.isEmpty() && !ssid.isEmpty(), WiFi.status() == WL_CONNECTED, mqttOnline.load(), imuHealthy,
          static_cast<unsigned long>(sentCount.load()), static_cast<unsigned long>(steps.steps), bluetoothState());
    }
    serialLine = ""; discardLine = false;
  }
}

void telemetry() {
  if (!imuHealthy) { Serial.println("SENSOR_ERROR imu_no_valid_sample"); return; }
  JsonDocument doc;
  doc["schema_version"] = 1; doc["firmware_version"] = VERSION;
  doc["source"] = "device"; doc["device_id"] = deviceId;
  doc["boot_id"] = bootId; doc["sample_seq"] = sequence++;
  doc["uptime_ms"] = uint64_t(esp_timer_get_time() / 1000);
  doc["accel_x_g"] = ax; doc["accel_y_g"] = ay; doc["accel_z_g"] = az;
  auto accel = doc["accel_g"].to<JsonArray>(); accel.add(ax); accel.add(ay); accel.add(az);
  auto gyro = doc["gyro_dps"].to<JsonArray>(); gyro.add(gx); gyro.add(gy); gyro.add(gz);
  if (athleteId) doc["athlete_id"] = athleteId; else doc["athlete_id"] = nullptr;
  doc["sessao"] = sessionId; doc["sessao_ativa"] = running;
  doc["duracao_s"] = activeMs / 1000; doc["passos"] = steps.steps;
  float distance = estimatedDistanceKm(steps.steps, stepLengthM);
  float calories = estimatedCalories(activeMs, weightKg, activityMet);
  if (isfinite(distance)) doc["distancia_km"] = distance; else doc["distancia_km"] = nullptr;
  if (isfinite(calories)) doc["calorias_kcal"] = calories; else doc["calorias_kcal"] = nullptr;
  if (isfinite(distance) && distance > 0) doc["ritmo_min_km"] = activeMs / 60000.0f / distance;
  else doc["ritmo_min_km"] = nullptr;
  doc["bpm"] = nullptr; doc["temperatura_pele_c"] = nullptr;
  doc["latitude"] = nullptr; doc["longitude"] = nullptr; doc["gps"] = "sem_modulo_configurado";
  doc["wifi"] = WiFi.status() == WL_CONNECTED ? "conectado" : "desconectado";
  doc["bluetooth"] = bluetoothState();
  if (batteryMv > 0) doc["battery_mv"] = batteryMv; else doc["battery_mv"] = nullptr;
  if (batteryPercent >= 0) doc["battery_percent_estimate"] = batteryPercent;
  else doc["battery_percent_estimate"] = nullptr;
  if (WiFi.status() == WL_CONNECTED) doc["wifi_rssi_dbm"] = WiFi.RSSI(); else doc["wifi_rssi_dbm"] = nullptr;
  doc["mqtt_connected"] = mqttOnline.load();
  auto quality = doc["measurement_status"].to<JsonObject>();
  quality["passos"] = "estimativa_mpu6886";
  quality["distancia"] = stepLengthM > 0 ? "estimativa_por_passos" : "sem_comprimento_passo";
  quality["calorias"] = weightKg > 0 && activityMet > 0 ? "estimativa_bruta_met_informado" : "sem_peso_ou_met";
  quality["bpm"] = "sensor_nao_configurado";
  quality["temperatura_pele"] = "sensor_nao_configurado";
  quality["gps"] = "sensor_nao_configurado";
  quality["bateria"] = "percentual_estimado_por_tensao";
  if (traceBatchSize) {
    doc["imu_trace_schema"] = 2;
    doc["imu_trace_dropped"] = traceDropped;
    auto batch = doc["imu_trace"].to<JsonArray>();
    for (size_t i = 0; i < traceBatchSize; ++i) {
      const auto& sample = traceBatch[i];
      auto row = batch.add<JsonArray>();
      row.add(sample.ms);
      // Inteiros compactos: aceleração/filtro em 0,0001 g, gyro em 0,01 °/s.
      for (float value : sample.accel) row.add(static_cast<int32_t>(lroundf(value * 10000)));
      for (float value : sample.gyro) row.add(static_cast<int32_t>(lroundf(value * 100)));
      row.add(static_cast<int32_t>(lroundf(sample.filtered * 10000)));
      row.add(sample.cadence); row.add(sample.pending); row.add(sample.event);
      row.add(sample.count); row.add(sample.active);
    }
    while (measureJson(doc) >= MAX_PAYLOAD && batch.size()) {
      batch.remove(batch.size() - 1); ++traceDropped;
    }
    doc["imu_trace_dropped"] = traceDropped;
    traceBatchSize = 0;
  }
  if (measureJson(doc) >= MAX_PAYLOAD) { Serial.println("TELEMETRY_ERROR payload_too_large"); return; }
  Message message{};
  serializeJson(doc, message.payload, sizeof(message.payload));
  // No modo MQTT, a transmissão USB de 10 payloads/s excederia 115200 baud
  // e atrasaria o IMU. O resumo USB normal volta ao encerrar o diagnóstico.
  if (!imuTrace || !imuTraceMqtt) Serial.printf("TELEMETRY %s\n", message.payload);
  if (outgoing) xQueueOverwrite(outgoing, &message);
  if (bleEnabled && bleCharacteristic) {
    uint8_t data[16] = {1, uint8_t((running ? 1 : 0) | (imuHealthy ? 2 : 0) |
                                (WiFi.status() == WL_CONNECTED ? 4 : 0) | (mqttOnline ? 8 : 0))};
    uint32_t count = steps.steps, seconds = activeMs / 1000;
    uint16_t mv = batteryMv > 0 ? batteryMv : 0xffff;
    memcpy(data + 2, &count, 4); memcpy(data + 6, &seconds, 4); memcpy(data + 10, &mv, 2);
    data[12] = batteryPercent >= 0 ? batteryPercent : 255;
    bleCharacteristic->setValue(data, sizeof(data));
    if (bleConnected) bleCharacteristic->notify();
  }
}

void drawStatus() {
  auto& screen = M5.Display;
  screen.fillScreen(TFT_BLACK); screen.setTextColor(TFT_WHITE); screen.setTextSize(1);
  screen.setCursor(4, 3); screen.printf("ATLETA  %s       %s", VERSION, running ? "ATIVO" : "PAUSA");
  screen.drawFastHLine(4, 16, 232, TFT_DARKGREY);
  if (page == 0) {
    screen.setCursor(4, 24); screen.setTextSize(2); screen.printf("Passos: %lu", static_cast<unsigned long>(steps.steps));
    screen.setTextSize(1); screen.setCursor(4, 49);
    screen.printf("Tempo ativo: %lu s  Bateria: %d%%\n", static_cast<unsigned long>(activeMs / 1000), batteryPercent);
    if (stepLengthM > 0) screen.printf("Distancia est.: %.3f km\n", estimatedDistanceKm(steps.steps, stepLengthM));
    else screen.println("Distancia: informe comprimento do passo");
    if (weightKg > 0 && activityMet > 0) screen.printf("Calorias est.: %.2f kcal\n", estimatedCalories(activeMs, weightKg, activityMet));
    else screen.println("Calorias: informe peso e MET");
    screen.printf("Wi-Fi: %s  MQTT: %s\n", WiFi.status() == WL_CONNECTED ? "OK" : "off", mqttOnline ? "OK" : "off");
    screen.printf("BLE: %s", bluetoothState());
  } else if (page == 1) {
    screen.setCursor(4, 25);
    screen.printf("MPU6886: %s\n\n", imuHealthy ? "respondendo" : "sem leitura");
    screen.printf("A: %+.3f %+.3f %+.3f g\n", ax, ay, az);
    screen.printf("G: %+.1f %+.1f %+.1f dps\n", gx, gy, gz);
    screen.printf("Bateria: %d mV (%% estimado)\n", batteryMv);
    screen.printf("MQTT envios: %lu | erro: %d\n", static_cast<unsigned long>(sentCount.load()), mqttError.load());
    screen.println("Passos: estimativa experimental");
  } else {
    screen.setCursor(4, 25); screen.setTextColor(TFT_YELLOW);
    screen.println("SENSORES EXTERNOS\n"); screen.setTextColor(TFT_WHITE);
    screen.println("BPM: sensor nao configurado");
    screen.println("Pele: sensor nao configurado");
    screen.println("GPS: modulo nao configurado\n");
    screen.println("Inspecao de conexoes por USB.");
  }
  screen.setTextColor(TFT_CYAN); screen.setCursor(4, 116);
  screen.println("A pausa | B tela | segure B: Bluetooth");
  screen.println("Segure A: nova sessao");
}
}

void setup() {
  pinMode(4, OUTPUT); digitalWrite(4, HIGH);
  Serial.setTxBufferSize(3072);
  auto cfg = M5.config();
  cfg.fallback_board = m5::board_t::board_M5StickCPlus2;
  cfg.serial_baudrate = 115200; cfg.internal_imu = true;
  cfg.internal_mic = false; cfg.internal_spk = false;
  cfg.external_imu = false; cfg.external_rtc = false;
  M5.begin(cfg);
  M5.Display.setRotation(1); M5.Display.setBrightness(65);
  M5.BtnA.setHoldThresh(1200); M5.BtnB.setHoldThresh(1200);
  loadConfig();
  snprintf(bootId, sizeof(bootId), "%08lx%08lx", static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random()));
  startSession();
  lastTick = esp_timer_get_time() / 1000;
  outgoing = xQueueCreate(1, sizeof(Message));
  if (xTaskCreatePinnedToCore(networkTask, "atleta-network", 8192, nullptr, 1, nullptr, 0) != pdPASS)
    Serial.println("NETWORK_ERROR task_memory");
  Serial.printf("ATLETA_LAB_READY firmware=%s board=M5StickCPlus2\n", VERSION);
  inventory(false); drawStatus();
}

void loop() {
  M5.update();
  uint32_t now = millis();
  uint64_t tick = esp_timer_get_time() / 1000;
  if (running) activeMs += tick - lastTick;
  lastTick = tick;
  if (M5.BtnA.wasHold()) startSession();
  else if (M5.BtnA.wasClicked()) { running = !running; steps.breakSequence(); }
  if (M5.BtnB.wasHold()) setBluetooth(!bleEnabled);
  else if (M5.BtnB.wasClicked()) page = (page + 1) % 3;
  if (bleRestart.exchange(false) && bleEnabled) BLEDevice::startAdvertising();
  readSerial();
  if (imuTrace && millis() - traceStarted >= MAX_TRACE_MS) stopImuTrace();
  if (now - lastImu >= IMU_MS) {
    lastImu = now;
    auto updated = M5.Imu.update();
    if (updated & m5::IMU_Class::sensor_mask_accel) {
      auto data = M5.Imu.getImuData();
      ax = data.accel.x; ay = data.accel.y; az = data.accel.z;
      gx = data.gyro.x; gy = data.gyro.y; gz = data.gyro.z;
      imuHealthy = isfinite(ax) && isfinite(ay) && isfinite(az) && isfinite(gx) && isfinite(gy) && isfinite(gz);
      if (imuHealthy) {
        lastGoodImu = now;
        if (running) steps.add(now, ax, ay, az, gx, gy, gz);
        traceImuSample(now);
      } else {
        steps.breakSequence();
      }
    } else if (imuHealthy && now - lastGoodImu > 200) {
      imuHealthy = false;
      steps.breakSequence();
    }
  }
  uint32_t telemetryInterval = imuTrace && imuTraceMqtt ? 100 : TELEMETRY_MS;
  if (now - lastTelemetry >= telemetryInterval) {
    lastTelemetry = now;
    batteryMv = M5.Power.getBatteryVoltage();
    batteryPercent = batteryMv > 0 ? M5.Power.getBatteryLevel() : -1;
    telemetry();
  }
  if (now - lastDisplay >= 500) { lastDisplay = now; drawStatus(); }
  delay(2);
}
