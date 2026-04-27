import os

from groq import Groq


api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise RuntimeError("GROQ_API_KEY env var is not set")

client = Groq(api_key=api_key)

try:
    print("Mengirim pesan ke Groq...")
    
    completion = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile"),
        messages=[
            {
                "role": "user",
                "content": "Halo! Bisa jelaskan singkat apa itu Groq LPU?",
            }
        ],
        temperature=float(os.getenv("GROQ_TEMPERATURE", "1")),
        max_completion_tokens=int(os.getenv("GROQ_MAX_COMPLETION_TOKENS", "512")),
        top_p=float(os.getenv("GROQ_TOP_P", "1")),
        stream=True,
    )

    for chunk in completion:
        print(chunk.choices[0].delta.content or "", end="")

except Exception as e:
    print(f"❌ Terjadi kesalahan: {e}")
