// Reprocessa as leituras de capture_steps.py com o detector C++ real.
#include "../src/activity.h"
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

int main(int argc, char** argv) {
  if (argc != 2) { std::fprintf(stderr, "Uso: step_counter_replay imu.csv\n"); return 1; }
  std::ifstream file(argv[1]);
  std::string line;
  if (!std::getline(file, line) || line.find("ms,ax_g,ay_g,az_g,") != 0) {
    std::fprintf(stderr, "CSV não encontrado ou formato inválido\n"); return 1;
  }
  StepCounter counter;
  uint32_t samples = 0;
  try {
    while (std::getline(file, line)) {
      std::istringstream stream(line);
      std::vector<std::string> fields;
      std::string value;
      while (std::getline(stream, value, ',')) fields.push_back(value);
      if (fields.size() != 13) throw std::runtime_error("amostra incompleta");
      if (std::stoul(fields[12])) {
        counter.add(static_cast<uint32_t>(std::stoul(fields[0])),
            std::stof(fields[1]), std::stof(fields[2]), std::stof(fields[3]),
            std::stof(fields[4]), std::stof(fields[5]), std::stof(fields[6]));
      } else { counter.breakSequence(); }
      ++samples;
    }
  } catch (const std::exception& error) {
    std::fprintf(stderr, "Erro na amostra %lu: %s\n", static_cast<unsigned long>(samples + 1), error.what());
    return 1;
  }
  if (!samples) { std::fprintf(stderr, "CSV sem amostras\n"); return 1; }
  std::printf("{\"samples\":%lu,\"replayed_steps\":%lu}\n",
      static_cast<unsigned long>(samples), static_cast<unsigned long>(counter.steps));
}
