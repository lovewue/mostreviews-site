from openai import OpenAI
import os

key = os.environ.get("OPENAI_API_KEY")

print("KEY FOUND:", bool(key))
print("FIRST 10:", key[:10] if key else None)

client = OpenAI(api_key=key)

response = client.responses.create(
    model="gpt-4.1-mini",
    input="Say hello"
)

print(response.output_text)
