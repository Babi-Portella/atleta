#pragma once
#include <cmath>
#include <cstdint>

// Detector para o pulso. Quatro picos com cadência plausível
// confirmam uma sequência; picos próximos demais não são passadas novas.
class StepCounter {
 public:
  // Diagnóstico de cada amostra; não muda as decisões do detector.
  enum class Event : uint8_t {
    SAMPLE = 0, FIRST_PEAK = 1, TOO_CLOSE = 2, RESTART_GAP = 3,
    RESTART_CADENCE = 4, CANDIDATE = 5, CONFIRMED = 6, COUNTED = 7,
    INVALID_SAMPLE = 8, SAMPLE_GAP = 9, EARLY_CADENCE = 10, MOTION_ARTIFACT = 11
  };
  uint32_t steps = 0;
  void reset() { *this = StepCounter(); }
  void breakSequence() { initialized = false; streak = 0; cadenceMs = 0; armed = true; }
  float filteredAcceleration() const { return filtered; }
  uint32_t cadenceInterval() const { return cadenceMs; }
  uint32_t pendingPeaks() const { return streak < CONFIRM_PEAKS ? streak : 0; }
  Event lastEvent() const { return event; }
  void add(uint32_t now, float x, float y, float z, float gx = 0, float gy = 0, float gz = 0) {
    event = Event::SAMPLE;
    const float magnitude = std::sqrt(x*x + y*y + z*z);
    const float rotation = std::sqrt(gx*gx + gy*gy + gz*gz);
    if (!std::isfinite(magnitude) || !std::isfinite(rotation) || magnitude < 0.2f || magnitude > 3.5f) {
      breakSequence(); artifactSince = now; artifactBlocked = true;
      event = Event::INVALID_SAMPLE; return;
    }
    // Rotações rápidas de manuseio não podem iniciar ou prolongar marcha.
    if (rotation > MAX_ROTATION_DPS) {
      breakSequence(); artifactSince = now; artifactBlocked = true;
      event = Event::MOTION_ARTIFACT; return;
    }
    if (artifactBlocked) {
      if (now - artifactSince < ARTIFACT_HOLDOFF_MS) {
        breakSequence(); event = Event::MOTION_ARTIFACT; return;
      }
      artifactBlocked = false;
    }
    if (!initialized || now - lastSample > 200) {
      baseline = magnitude; filtered = 0; initialized = true; lastSample = now;
      streak = 0; cadenceMs = 0; armed = true; event = Event::SAMPLE_GAP; return;
    }
    lastSample = now;
    baseline += 0.02f * (magnitude - baseline);
    // Com amostras a ~50 Hz, reduz oscilações rápidas dentro de uma passada.
    filtered += 0.25f * (magnitude - baseline - filtered);
    if (filtered < REARM_G) armed = true;
    // Uma marcha já confirmada aceita impactos menores; após a parada,
    // a confirmação volta a exigir o limiar inicial mais conservador.
    const float peakThreshold = streak >= CONFIRM_PEAKS && now - lastPeak <= MAX_STEP_MS
        ? TRACK_PEAK_G : PEAK_G;
    if (!armed || filtered < peakThreshold) return;
    armed = false;
    if (!streak) { streak = 1; lastPeak = now; event = Event::FIRST_PEAK; return; }
    const uint32_t interval = now - lastPeak;
    if (interval < MIN_STEP_MS) { event = Event::TOO_CLOSE; return; }
    // Um pico antecipado não substitui a referência da passada anterior.
    // Reiniciar aqui desorganizava uma sequência válida por um pico extra.
    if (streak >= 2 && interval * 100u < cadenceMs * MIN_CADENCE_PERCENT) {
      event = Event::EARLY_CADENCE; return;
    }
    lastPeak = now;
    // A partida e a desaceleração podem mudar o intervalo em mais de 30%.
    // Não descartar esses passos; manter os limites de frequência e amplitude.
    if (interval > MAX_STEP_MS || (streak >= 2 &&
         interval * 100u > cadenceMs * MAX_CADENCE_PERCENT)) {
      streak = 1; cadenceMs = 0;
      event = interval > MAX_STEP_MS ? Event::RESTART_GAP : Event::RESTART_CADENCE;
      return;
    }
    if (streak == 1) { streak = 2; cadenceMs = interval; event = Event::CANDIDATE; return; }
    cadenceMs = (cadenceMs * 3u + interval) / 4u;
    if (streak < CONFIRM_PEAKS) {
      ++streak;
      event = Event::CANDIDATE;
      if (streak == CONFIRM_PEAKS) { steps += CONFIRM_PEAKS; event = Event::CONFIRMED; }
    } else {
      ++steps;
      event = Event::COUNTED;
    }
  }
 private:
  static constexpr uint32_t MIN_STEP_MS = 320, MAX_STEP_MS = 1500;
  static constexpr uint32_t ARTIFACT_HOLDOFF_MS = 1200;
  static constexpr float MAX_ROTATION_DPS = 400;
  static constexpr uint32_t CONFIRM_PEAKS = 4;
  static constexpr uint32_t MIN_CADENCE_PERCENT = 50, MAX_CADENCE_PERCENT = 150;
  static constexpr float REARM_G = 0.02f, PEAK_G = 0.11f, TRACK_PEAK_G = 0.06f;
  bool initialized = false, armed = true, artifactBlocked = false;
  Event event = Event::SAMPLE;
  float baseline = 1, filtered = 0;
  uint32_t lastSample = 0, lastPeak = 0, cadenceMs = 0, streak = 0, artifactSince = 0;
};

inline float estimatedDistanceKm(uint32_t steps, float stepLengthM) {
  return stepLengthM > 0 ? steps * stepLengthM / 1000.0f : NAN;
}
inline float estimatedCalories(uint64_t activeMs, float weightKg, float met) {
  // Energia bruta por MET; intensidade informada no perfil, não medida pelo sensor.
  return weightKg > 0 && met > 0 ? met * weightKg * activeMs / 3600000.0f : NAN;
}
