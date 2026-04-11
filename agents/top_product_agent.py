import json
import os
from pathlib import Path
from openai import OpenAI
from tools import Tools


client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


class TopProductAgent:
    def __init__(self, month: str):
        self.month = month
        self.tools = Tools(month)
        self.evidence = []

    def run(self):
        print(f"\nAGENT STARTING: {self.month}\n")

        top20 = self.tools.get_top20_month()
        top100 = self.tools.get_top100_last12()

        context = {
            "month": self.month,
            "top20_sample": top20[:10],
            "top100_sample": top100[:10],
        }

        print("Initial listing inspection...\n")

        for p in top20:
            sku = p["sku"]
            print("Inspecting listing first:", sku)

            result = self.tools.get_listing(sku)

            self.evidence.append({
                "action": "inspect_listing",
                "sku": sku,
                "result": result,
            })

        for i in range(6):
            print(f"\n--- Agent step {i + 1} ---")

            decision = self.ask_agent(context)
            print("Decision:", decision)

            action = decision.get("action")

            if action == "compare":
                print("Running compare:", decision["group_by"])
                result = self.tools.compare(self.month, decision["group_by"])
                self.evidence.append({
                    "action": "compare",
                    "group_by": decision["group_by"],
                    "result": result,
                })

            elif action == "aggregate":
                print("Running aggregate:", decision)
                result = self.tools.aggregate(
                    decision["set_name"],
                    self.month,
                    decision["group_by"],
                )
                self.evidence.append({
                    "action": "aggregate",
                    "set_name": decision["set_name"],
                    "group_by": decision["group_by"],
                    "result": result,
                })

            elif action == "title_terms":
                print("Running title terms:", decision["set_name"])
                result = self.tools.title_terms(
                    decision["set_name"],
                    self.month,
                )
                self.evidence.append({
                    "action": "title_terms",
                    "set_name": decision["set_name"],
                    "result": result,
                })

            elif action == "inspect_product":
                print("Inspecting product:", decision["sku"])
                result = self.tools.get_product(decision["sku"])
                self.evidence.append({
                    "action": "inspect_product",
                    "sku": decision["sku"],
                    "result": result,
                })

            elif action == "inspect_listing":
                print("Inspecting listing:", decision["sku"])
                result = self.tools.get_listing(decision["sku"])
                self.evidence.append({
                    "action": "inspect_listing",
                    "sku": decision["sku"],
                    "result": result,
                })

            elif action == "finish":
                print("Agent finished early")
                break

            else:
                print("Unknown action, stopping:", action)
                break

        print("\nBuilding report...\n")
        report = self.build_report(context)
        self.save_report(report)
        return report

    def ask_agent(self, context):
        prompt = f"""
You are an autonomous ecommerce analysis agent.

Goal:
Explain why the top 20 NOTHS products for {self.month} may be performing, using the top 100 products from the last 12 months as context.

You have:
1. Initial dataset context
2. Evidence from prior tool calls

You must decide the SINGLE best next action.

Available actions:
- compare(group_by)
- aggregate(set_name, group_by)
- title_terms(set_name)
- inspect_product(sku)
- inspect_listing(sku)
- finish

Allowed group_by values:
- personalised
- seller
- available
- rating_band
- review_band
- occasion

Allowed set_name values:
- top20
- top100

Return JSON only, one of these forms:
{{"action":"compare","group_by":"personalised"}}
{{"action":"aggregate","set_name":"top20","group_by":"seller"}}
{{"action":"title_terms","set_name":"top20"}}
{{"action":"inspect_product","sku":"1544832"}}
{{"action":"inspect_listing","sku":"1544832"}}
{{"action":"finish"}}

Guidance:
- Use compare() to test whether a pattern is stronger in the Top 20 than the Top 100.
- Use title_terms() when you want to inspect recurring words.
- Use inspect_product() for metadata inspection.
- Use inspect_listing() when you want to inspect listing strength, such as title richness, description length, image count, price visibility, and keyword intent.
- Finish when you have enough evidence.

Initial context:
{json.dumps(context, indent=2)}

Evidence so far:
{json.dumps(self.evidence, indent=2)}
"""
        print("Calling OpenAI for next action...")

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
        )

        raw = response.output_text.strip()
        print("Raw model response:", raw)

        return self.safe_json_loads(raw)

    def build_report(self, context):
        prompt = f"""
You are an ecommerce analysis agent.

Write a structured analysis of why the top 20 NOTHS products for {self.month} may be performing.

Use:
- the initial context
- the gathered evidence

Focus especially on:
- title keyword richness
- occasion language
- personalisation usage
- seller concentration
- listing quality signals
- whether any findings are strong vs weak
- whether promotion cannot be ruled out

Be careful:
- do not claim certainty
- distinguish evidence from hypothesis
- mention caveats
- note where metadata is strong but listing evidence is incomplete

Return JSON with these keys:
- summary
- strong_patterns
- weaker_patterns
- exceptions
- seller_takeaways
"""
        print("Calling OpenAI for final report...")

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=(
                prompt
                + "\n\nContext:\n"
                + json.dumps(context, indent=2)
                + "\n\nEvidence:\n"
                + json.dumps(self.evidence, indent=2)
            ),
        )

        raw = response.output_text.strip()
        print("Raw final report:", raw)

        parsed = self.safe_json_loads(raw)
        if isinstance(parsed, dict):
            return parsed

        return {
            "summary": "Agent produced a non-JSON response.",
            "strong_patterns": [],
            "weaker_patterns": [],
            "exceptions": [],
            "seller_takeaways": [],
            "raw_output": raw,
        }

    def save_report(self, report):
        output_dir = Path(__file__).resolve().parent / "output"
        output_dir.mkdir(exist_ok=True)

        output_path = output_dir / f"{self.month}_analysis.json"

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\nSaved report to: {output_path}")

    @staticmethod
    def safe_json_loads(text):
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except json.JSONDecodeError:
                    continue

        raise ValueError(f"Could not parse JSON from model output:\n{text}")


if __name__ == "__main__":
    agent = TopProductAgent("2026-03")
    report = agent.run()

    print("\nFINAL REPORT:\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
