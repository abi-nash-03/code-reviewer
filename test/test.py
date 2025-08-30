import os
from openai import OpenAI
from dotenv import load_dotenv
import subprocess
from fastapi import FastAPI, Request, Header
import uvicorn
import hmac
import hashlib
import json
import requests

load_dotenv()


# create an app instance
app = FastAPI()

def get_staged_files():
	result = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True)
	return result.stdout.splitlines()

def format_pr_diff(diff_text):
	diff_text_json = json.loads(diff_text)
	diff_arr = []
	for file in diff_text_json['files']:
		arr = {}
		arr['file_name'] = file['filename']
		arr['status'] = file['status']
		arr['patch'] = file.get('patch')
		diff_arr.append(arr)
  
	return json.dumps(diff_arr)

def get_pr_diff(diff_url: str):
	auth_token = os.environ.get('GITHUB_TOKEN')
	headers = {"Authorization": f"token {auth_token}"}
	resp = requests.get(diff_url, headers=headers)
	if resp.status_code == 200:
		return resp.text
	else:
		raise Exception(f"Failed to fetch diff: {resp.status_code}, {resp.text}")


@app.get("/")
def root():
	return {"message": "Hello, World!"}

@app.get("/check-route/")
async def check(
	request: Request,
	x_hub_signature_256: str = Header(None),   # GitHub signs requests with this,
	x_github_event: str = Header(None)
	):
	print("------------REQUEST-------------")

	# Method & URL
	print("Method:", request.method)
	print("URL:", request.url)

	# Headers
	print("Headers:", dict(request.headers))

	# Query params
	print("Query Params:", dict(request.query_params))

	# Body
	try:
		body_bytes = await request.body()
		body_str = body_bytes.decode("utf-8")
		print("Raw Body:", body_str)

		try:
			body_json = json.loads(body_str)
			print("JSON Body:", json.dumps(body_json, indent=2))
		except Exception:
			pass
	except Exception as e:
		print("Error reading body:", e)
	return {"message": "Hello, check!"}


@app.post("/webhook/github")
async def github_webhook(
	request: Request,
	x_hub_signature_256: str = Header(None),   # GitHub signs requests with this
	x_github_event: str = Header(None)
):
	# body = await request.body()
	print("------------REQUEST-------------")

	# Method & URL
	print("Method:", request.method)
	print("URL:", request.url)

	# Headers
	print("Headers:", dict(request.headers))

	# Query params
	print("Query Params:", dict(request.query_params))
	body_json = None

	# Body
	try:
		body_bytes = await request.body()
		body = await request.body()
		body_str = body_bytes.decode("utf-8")
		# print("Raw Body:", body_str)

		try:
			body_json = json.loads(body_str)
			print("----------------------------------------------------------")
			print("JSON Body:", json.dumps(body_json, indent=2))
		except Exception:
			pass
	except Exception as e:
		print("Error reading body:", e)

	# ✅ Verify GitHub signature
	github_secret = os.environ.get('GITHUB_SECRET')

	if github_secret:
		# Convert secret to bytes
		secret_bytes = github_secret.encode("utf-8")

		signature = "sha256=" + hmac.new(secret_bytes, body, hashlib.sha256).hexdigest()
		if not hmac.compare_digest(signature, x_hub_signature_256):
			return {"status": "invalid signature"}

	print("----------------------------signature verified successfully--------------------------")

	# payload = await request.json()
	payload = body_json
	# print('=================payload============')
	# print(payload)
 
	if payload is None:
		return

	if x_github_event == "pull_request":
		action = payload["action"]
		pr_number = payload["pull_request"]["number"]
		repo = payload["repository"]["full_name"]

		if action not in ["opened", "synchronize"]:
			return

		# 🔥 handle PR creation/update here
		print(f"PR {pr_number} in {repo} was {action}")
		pull_request = payload['pull_request']
		repository = payload['repository']
		compare_url = repository['compare_url']
		base_sha = None
		head_sha = None
		if 'head' in pull_request:
			head_sha = pull_request['head']['sha']
		if 'base' in pull_request:
			base_sha = pull_request['base']['sha']

		if base_sha is None or head_sha is None:
			return
		
		compare_url = compare_url.replace("{base}", base_sha)
		compare_url = compare_url.replace("{head}", head_sha)
		diff_text = get_pr_diff(compare_url)
		formatted_diff_text = format_pr_diff(diff_text)
		print('-------------------formatted text---------------')
		print(formatted_diff_text)
  
		get_suggesstions_from_openAi(formatted_diff_text)



def get_prompt(code_diff):
	'''
	This function will return the prompt
	'''
	prompt = f'''
			You are a senior software engineer reviewing a pull request.
			Here are the code changes (diff format):
   
			{code_diff}
   
			Please provide a detailed code review: highlight potential bugs,
			security issues, style problems, and suggest improvements.
   
			OUTPUT FORMAT(only the following output)
			An array of review comments

			[
				{
					'path' : 'src/sample.txt', #relative_path_to_the_file
					'position' : '2', #line number to which i need to add the comment
					'body' : 'need some improvement' #actual review suggestions
				},
				{
					...
				}
			]
   
 			'''
	
	return prompt
	
def get_suggesstions_from_openAi(diff_text):
	prompt = get_prompt(diff_text)
	api_key = os.getenv("OPENAI_API_KEY")

	client = OpenAI(
		api_key= api_key,
	)
	response = client.chat.completions.create(
		model="gpt-5-mini-2025-08-07",
		messages=[
			{"role": "system", "content": "You are a senior code reviewer. Provide improvements and fixes."},
			{"role": "user", "content": prompt}
		]
	)
 
	print('=================openAI response=================')
	print(response.choices[0].message.content)


def main():
	uvicorn.run(app, host="0.0.0.0", port=8200)	


if __name__ == "__main__":
	main()
