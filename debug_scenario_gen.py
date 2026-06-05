"""Debug why generate_base_scenarios only returns 2 scenarios."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.dsl.compiler import compile_dsl
from src.instruction_parser.auto_parser import InstructionParser
from src.evaluators.coverage_driven_scenario_generator import CoverageDrivenScenarioGenerator
from src.llm_client import DeepSeekClient

# Load the same instruction
instruction_file = Path("data/instructions/task_001_rider_flying_leg.txt")
raw_instruction = instruction_file.read_text(encoding="utf-8")

# Parse
llm = DeepSeekClient()
parser = InstructionParser(llm)
parsed_task = parser.parse(raw_instruction)

# Compile DSL
dsl = compile_dsl(parsed_task)

# Generate scenarios
generator = CoverageDrivenScenarioGenerator(dsl)
scenarios = generator.generate_base()

print(f"Total scenarios generated: {len(scenarios)}")
for i, scenario in enumerate(scenarios, 1):
    print(f"{i}. {scenario['name']}")

print(f"\nDSL has FAQ: {bool(dsl.faq)}")
print(f"FAQ count: {len(dsl.faq) if dsl.faq else 0}")
