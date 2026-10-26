"""Run the bounded reproducible offline A/B/C workflow benchmark."""

import argparse
import json

from eng.benchmark import SCENARIOS, run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--scenario", action="append", choices=SCENARIOS)
    args = parser.parse_args()
    print(
        json.dumps(
            run_benchmark(repetitions=args.repetitions, seed=args.seed, scenarios=args.scenario),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
