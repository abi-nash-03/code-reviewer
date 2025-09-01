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

# global variables
commit_id = None
pr_number = None
repository_name = None
owner = None

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
	global commit_id, pr_number, repository_name, owner
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
		pull_request = payload['pull_request']
		pr_number = pull_request["number"]
		repo = payload["repository"]["full_name"]
		repository = payload['repository']
		compare_url = repository['compare_url']
		repository_name = repository['name']
		owner = repository['owner']['login']
  
		base_sha = None
		head_sha = None
  
  
		if action not in ["opened", "synchronize"]:
			return

		if action == 'opened':
			head_sha = pull_request['head']['sha']
			base_sha = pull_request['base']['sha']
			
   
		if action == 'synchronize':
			head_sha = payload['after']
			base_sha = payload['before']
   
		commit_id = head_sha
   
		# # 🔥 handle PR creation/update here
		# print(f"PR {pr_number} in {repo} was {action}")

		# create the compare URL
		compare_url = compare_url.replace("{base}", base_sha)
		compare_url = compare_url.replace("{head}", head_sha)
		diff_text = get_pr_diff(compare_url)
		formatted_diff_text = format_pr_diff(diff_text)
  
		print('-------------------formatted text---------------')
		print(formatted_diff_text)
  
		get_suggesstions_from_openAi(formatted_diff_text)



def get_prompt(code_diff: str) -> str:
	"""
	Generate a prompt for reviewing a GitHub PR diff.
	"""
 
	prompt = f"""
	You are a senior software engineer reviewing a pull request. 
	Carefully analyze the following code changes (in unified diff format):

	{code_diff}

	Your task:
	- Identify bugs, security issues, performance problems, and style violations.
	- Suggest clear, actionable improvements.

	Output requirements:
	- Return ONLY a JSON array (no extra text, no explanations).
	- Each element should follow this schema:
	- line , actual file line number
	{{
		"path": "relative/file/path.ext",   // file path from the diff
		"line": 12,                     // line number in the actual file (integer)
		"body": "Your comment text here"    // concise review suggestion
	}}

	Example output:
	[
	{{
		"path": "src/sample.txt",
		"line": 2,
		"body": "Consider using a constant instead of a magic number."
	}},
	{{
		"path": "src/utils/helper.py",
		"line": 15,
		"body": "Possible off-by-one error in loop index."
	}}
	]
	"""
	return prompt

def format_bulk_review_suggestions(review_text):
	review_text_json = json.loads(review_text)
	result = {
		'body' : 'Automated code review',
		'event' : 'COMMENT',
		'comments' : review_text_json
	}
 
	print("-------------bulk review text---------------")
	print(result)

	return result

def add_comments_to_pr(review_comments):
	auth_token = os.environ.get('GITHUB_TOKEN')
	headers = {"Authorization": f"token {auth_token}"}
	
	url = f"https://api.github.com/repos/{owner}/{repository_name}/pulls/{pr_number}/reviews"
	response = requests.post(url, headers=headers, json=review_comments)
	print("==========add comment response===================")
	print(response.json())
	if response.status_code == 200:
		return "Review added successfully"	
	else:
		raise Exception(f"Failed to add comments to pr: {response.status_code}, {response.text}")

def get_suggesstions_from_openAi(diff_text):
	api_key = os.getenv("OPENAI_API_KEY")
	prompt = get_prompt(diff_text)

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
	review_suggestions = response.choices[0].message.content
	print(f'=============type = {type(review_suggestions)}')
	formatted_review = format_bulk_review_suggestions(review_suggestions)
	add_comments_to_pr(formatted_review)

def main():
	uvicorn.run(app, host="0.0.0.0", port=8200)	


if __name__ == "__main__":
	main()
