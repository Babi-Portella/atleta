// Zig em -O2 define NDEBUG; os testes precisam continuar executando os asserts.
#ifdef NDEBUG
#undef NDEBUG
#endif
#include "../src/activity.h"

#include <cassert>
#include <cmath>
#include <cstdio>
#include <vector>

constexpr float PI = 3.14159265358979323846f;

uint32_t sineSteps(float frequency, float amplitude, uint32_t durationMs = 10000) {
  StepCounter counter;
  for (uint32_t t = 0; t < durationMs; t += 20) {
    counter.add(t, 0, 0, 1 + amplitude * std::sin(2 * PI * frequency * t / 1000));
  }
  return counter.steps;
}

uint32_t bumpSteps(const std::vector<float>& seconds, uint32_t durationMs = 12000) {
  StepCounter counter;
  for (uint32_t t = 0; t < durationMs; t += 20) {
    float magnitude = 1;
    for (float second : seconds) {
      float delta = (t - second * 1000) / 65;
      magnitude += 0.3f * std::exp(-delta * delta);
    }
    counter.add(t, 0, 0, magnitude);
  }
  return counter.steps;
}

int main() {
  assert(sineSteps(2, 0.23f) == 20);
  assert(sineSteps(2, 0.10f) == 0);
  assert(sineSteps(4, 0.23f) <= 23);  // Picos duplos não viram 40 passos.

  StepCounter stationary, rotation;
  for (uint32_t t = 0; t < 10000; t += 20) {
    float phase = 2 * PI * 2 * t / 1000;
    stationary.add(t, 0, 0, 1);
    rotation.add(t, std::sin(phase), 0, std::cos(phase));
  }
  assert(stationary.steps == 0);
  assert(rotation.steps == 0);

  assert(bumpSteps({0.5f, 1.0f, 2.6f, 3.1f, 4.7f, 5.2f,
                    6.8f, 7.3f, 8.9f, 9.4f}) == 0);
  std::vector<float> regular;
  for (int i = 0; i < 20; ++i) regular.push_back(0.5f + i * 0.5f);
  assert(bumpSteps(regular) == 20);

  // Mudanças moderadas de ritmo não devem descartar passos na partida
  // nem deixar o fim de uma caminhada já confirmada aguardando quatro picos.
  assert(bumpSteps({0.5f, 1.0f, 1.5f, 2.22f, 2.72f, 3.22f, 3.72f, 4.22f}) == 8);
  assert(bumpSteps({0.5f, 1.0f, 1.5f, 2.0f, 2.72f, 3.44f, 4.16f}) == 7);
  assert(bumpSteps({0.5f, 1.4f, 1.9f, 2.4f, 2.9f, 3.4f, 3.9f, 4.4f}) == 8);

  // Um pico extra precoce entre passadas de 1 s não pode deslocar a
  // referência e apagar toda a sequência. O detector anterior contava zero.
  assert(bumpSteps({0.5f, 1.5f, 1.9f, 2.5f, 3.5f, 4.5f}) == 5);

  // Quatro impactos fortes confirmam marcha; impactos mais fracos em seguida
  // continuam contando. Um impacto fraco depois da pausa não confirma marcha.
  StepCounter tracking;
  for (uint32_t t = 0; t < 7000; t += 20) {
    float magnitude = 1;
    for (int index = 0; index < 9; ++index) {
      float second = index < 8 ? 0.5f + index * 0.5f : 6.0f;
      float delta = (t - second * 1000) / 65;
      magnitude += (index < 4 ? 0.3f : 0.18f) * std::exp(-delta * delta);
    }
    tracking.add(t, 0, 0, magnitude);
  }
  assert(tracking.steps == 8);

  // Aceleração ritmada durante rotação rápida é manuseio. Depois de parar
  // e respeitar o intervalo de recuperação, marcha normal volta a contar.
  StepCounter handling;
  bool sawMotionArtifact = false;
  for (uint32_t t = 0; t < 8000; t += 20) {
    float magnitude = 1;
    if (t < 3000) magnitude += 0.23f * std::sin(2 * PI * 2 * t / 1000);
    for (float second : {5.0f, 5.5f, 6.0f, 6.5f}) {
      float delta = (t - second * 1000) / 65;
      magnitude += 0.3f * std::exp(-delta * delta);
    }
    handling.add(t, 0, 0, magnitude, 0, 0, t < 3000 ? 500 : 0);
    sawMotionArtifact |= handling.lastEvent() == StepCounter::Event::MOTION_ARTIFACT;
    if (t < 5000) assert(handling.steps == 0);
  }
  assert(sawMotionArtifact && handling.steps == 4);

  // Batidas isoladas e alternância irregular continuam sem confirmar marcha.
  assert(bumpSteps({0.5f, 1.0f, 1.5f}) == 0);
  assert(bumpSteps({0.5f, 1.0f, 1.9f, 2.4f, 3.3f, 3.8f, 4.7f, 5.2f}) == 0);

  // A limitação atual aparece no diagnóstico: três picos após uma parada
  // ainda são candidatos, sem aumentar o total da caminhada anterior.
  assert(bumpSteps({0.5f, 1.0f, 1.5f, 2.0f, 2.5f, 5.0f, 5.5f, 6.0f}) == 5);
  StepCounter diagnostic;
  bool sawConfirmation = false, sawCount = false, sawGapRestart = false;
  for (uint32_t t = 0; t < 7000; t += 20) {
    float magnitude = 1;
    for (float second : {0.5f, 1.0f, 1.5f, 2.0f, 2.5f, 5.0f, 5.5f, 6.0f}) {
      float delta = (t - second * 1000) / 65;
      magnitude += 0.3f * std::exp(-delta * delta);
    }
    diagnostic.add(t, 0, 0, magnitude);
    sawConfirmation |= diagnostic.lastEvent() == StepCounter::Event::CONFIRMED;
    sawCount |= diagnostic.lastEvent() == StepCounter::Event::COUNTED;
    sawGapRestart |= diagnostic.lastEvent() == StepCounter::Event::RESTART_GAP;
  }
  assert(sawConfirmation && sawCount && sawGapRestart);
  assert(diagnostic.steps == 5 && diagnostic.pendingPeaks() == 3);

  std::puts("step_counter_native: OK");
}
