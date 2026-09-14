import asyncio
import os

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_ext.models.openai import OpenAIChatCompletionClient

client = OpenAIChatCompletionClient(
    model="openai/gpt-oss-120b",
    api_key=os.environ["GROQ_API_KEY"],
    base_url="http://localhost:8000/v1",
    max_tokens=400,
    model_info={
        "vision": False,
        "function_calling": False,
        "json_output": False,
        "family": "unknown",
        "structured_output": False,
    },
)

SHORT = " Answer in 2 sentences maximum. No tables. No lists."

a = AssistantAgent(
    "cost_agent",
    model_client=client,
    system_message=(
        "Your only goal is minimizing cost. You must never accept any spec "
        "that costs more than $30 per month. Reject any expensive proposal "
        "and restate your own proposal." + SHORT
    ),
)

b = AssistantAgent(
    "quality_agent",
    model_client=client,
    system_message=(
        "Your only goal is maximizing quality. You must never accept any spec "
        "with less than 32GB RAM. Reject any cheap proposal "
        "and restate your own proposal." + SHORT
    ),
)

team = RoundRobinGroupChat([a, b], termination_condition=MaxMessageTermination(20))


async def main():
    async for msg in team.run_stream(
        task="Decide on ONE server spec. You must agree."
    ):
        src = getattr(msg, "source", "?")
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            print(f"\n[{src}] {content}")


asyncio.run(main())