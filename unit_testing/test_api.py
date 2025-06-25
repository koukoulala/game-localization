from google import genai

client = genai.Client(api_key="AIzaSyB63FJn0UhSW4NmotKa1tN0EnPGx_v7f0Q")

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Explain how AI works in a few words",
)

print(response.text)