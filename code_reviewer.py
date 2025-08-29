import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


def get_staged_files():
    result = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True)
    return result.stdout.splitlines()


def get_prompt(code):
	'''
	This function will return the prompt
	'''
	prompt = f'''
			i want you to review my code.
			Im using php 8.3 and laravel 10
   
			here is the code
			{code}
 			'''
    


def main():
	api_key = os.getenv("OPENAI_API_KEY")

	client = OpenAI(
		api_key= api_key,
	)
	
	prompt = get_prompt('')
 
	response = client.responses.create(
	model="gpt-5-mini-2025-08-07",
	instructions="You are a senior code reviewer.",
	input=prompt,
	)

	print(response.output_text)


if __name__ == "__main__":
    main()