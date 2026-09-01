from transformers import AutoTokenizer, AutoModelForCausalLM

MODELS = [
    "HuggingFaceTB/SmolLM2-360M-Instruct", 
    "HuggingFaceTB/SmolLM2-135M-Instruct", 
    "Qwen/Qwen2.5-0.5B-Instruct", 
    "TinyLlama/TinyLlama-1.1B-Chat-v1.0"]

tokenizer = AutoTokenizer.from_pretrained(MODELS[1])
model = AutoModelForCausalLM.from_pretrained(MODELS[1])
prompt = (
    "Write short, casual dating bio in first person as a bird. "
    "Do not mention its name, species, or location."
    "Write exactly one short sentence, no more than 20 words. "
    "Output only the bio."
)

def generate(model=model, tokenizer=tokenizer, prompt=prompt):
    messages = [
        {"role": "user", "content": prompt}
    ]

    input_text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    inputs = tokenizer(input_text, return_tensors="pt")

    outputs = model.generate(
        **inputs,
        max_new_tokens=60,
        do_sample=True,
        temperature=0.9,
        top_p=0.9,
    )

    generated_tokens = outputs[0][inputs["input_ids"].shape[1]:]
    text = tokenizer.decode(
        generated_tokens,
        skip_special_tokens=True
    )
    return text

def is_valid(text):
    BAD_START = [
            "sure",
            "here's",
            "here is",
            "as an ai",
            "i can",
            "of course",
    ]

    FORBIDDEN = [
            "chat",
            "chatbot",
            "model",
            "ai assistant",
            "assistant",
            "[name]",
            "named",
            "[city]",
            "bio",
        ]
    
    text_lower = text.lower().strip()
    return (
        5 <= len(text.split()) <= 50
        and not any(word in text_lower for word in FORBIDDEN)
        and not "[" in text and not "]" in text
        and not any(text_lower.startswith(start) for start in BAD_START)
    )

def generate_bio():
    for _ in range(5):
        text = generate(model=model, tokenizer=tokenizer, prompt=prompt)
        print(f"Generated bio: {text}")
        print(f"Is valid: {is_valid(text)}")
        if is_valid(text):
            return text.strip().strip('"').strip("'")
    return None
