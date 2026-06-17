"""CLI entrypoint:  python -m infrapilot "Ollama pod is stuck Pending in ns ai"

With no argument, runs a default health-sweep prompt — handy as a one-shot
container command or a cron-style check.
"""
import sys

from .agent import diagnose

DEFAULT = (
    "Do a quick health sweep of the platform: is the GPU node schedulable, are "
    "the ollama and open-webui pods healthy in namespace 'ai', and is GPU "
    "utilization/VRAM in a sane range? Report anything off."
)


def main() -> None:
    symptom = " ".join(sys.argv[1:]).strip() or DEFAULT
    print(diagnose(symptom))


if __name__ == "__main__":
    main()
