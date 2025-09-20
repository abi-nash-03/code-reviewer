'''
This python script will review the last committed changes and add comments to the PR
'''
import os
from openai import OpenAI
from dotenv import load_dotenv
import subprocess
from fastapi import FastAPI, Request, Header, BackgroundTasks
import uvicorn
import hmac
import hashlib
import json
import requests
from config import redis


load_dotenv()


# create an app instance
app = FastAPI()
redis_conn = redis.redis_conn

# global variables
commit_id = None
pr_number = None
repository_name = None
owner = None

def get_pr_diff_bitbucket(head_hash, base_hash):
	'''
	This will get the diff in code from the bitbucket
 	'''
  
	auth_token = os.environ.get('BITBUCKET_TOKEN')
	headers = {"Authorization": f"Bearer {auth_token}"}
	workspace = os.environ.get('BITBUCKET_WORKSPACE')
	repo_slug = os.environ.get('BITBUCKET_REPO_SLUG')
 
	diff_url = f'https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/diff/{head_hash}..{base_hash}'
 
	resp = requests.get(diff_url, headers=headers)
	if resp.status_code == 200:
		return resp.text
	else:
		raise Exception(f"Failed to fetch diff from bitbucket: {resp.status_code}, {resp.text}")



def get_prompt_bitbucket(code_diff: str) -> str:
	"""
	Generate a prompt for reviewing a Bitbucket PR diff.
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
	{{
		"content": {{
			"raw": "Unused import random" // concise review suggestion
		}},
		"inline": {{
			"path": "src/sample.py",   // relative path in repo
			"to": 3                 // line number in the actual file (integer)
		}}
	}}

	Example output:
	[
	{{
		"content": {{
			"raw": "Consider using a constant instead of a magic number."
		}},
		"inline": {{
			"path": "src/sample.txt",
			"to": 2
		}}
	}},
	{{
		"content": {{
			"raw": "Possible off-by-one error in loop index."
		}},
		"inline": {{
			"path": "src/utils/helper.py",
			"to": 15
		}}
	}}
	]
	"""
	return prompt


def get_suggestions_from_openAi(prompt):
	"""
	This will get the suggestions from the open-ai in the defined format
	"""
	
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
 
	review_suggestions = response.choices[0].message.content
 
	return review_suggestions


def add_comments_to_pr_bitbucket(pr_id, suggestions):
	"""
	This will add connects to the PR
		-Bulk comments are not supported in bitbucket
		-So comments are added through individual api calls
	"""
	
	suggestions_json = json.loads(suggestions)
	workspace = os.environ.get('BITBUCKET_WORKSPACE')
	repo_slug = os.environ.get('BITBUCKET_REPO_SLUG')
	auth_token = os.environ.get('BITBUCKET_TOKEN')
	headers = {"Authorization": f"Bearer {auth_token}"}
 
 
	comment_url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/comments"

	for suggestion in suggestions_json:
		try:
			response = requests.post(comment_url, headers=headers, json=suggestion)
			if response.status_code == 200:	
				print("Review added successfully")
			else:
				print("Falied to add review.")
				raise Exception(f"Failed to add comments to pr: {response.status_code}, {response.text}")	
		except Exception as e:
			pass

def is_merge_commit(commit_hash):
	'''
	This will return whether a commit is a merge commit or a normal commit
		-This will check the parent of the commit if was made through bitbucket
		-This will also check whether the commit message has 'merge' in it, in-order to skip reviewing the merge commit from local
	'''
	
	workspace = os.environ.get('BITBUCKET_WORKSPACE')
	repo_slug = os.environ.get('BITBUCKET_REPO_SLUG')
	auth_token = os.environ.get('BITBUCKET_TOKEN')
	headers = {"Authorization": f"Bearer {auth_token}"}
 
	url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/commit/{commit_hash}"
	try:
		response = requests.get(url, headers=headers)
		commit_details = response.json()
		parents = commit_details['parents']
		commit_message = commit_details['message']
  
		# if more than 1 parent then it is merge commit
		if len(parents) > 1:
			# print("more than one parent")
			return True

		if 'merge' in commit_message.lower():
			# print("merge in commit message")
			return True

		return False
	except Exception as e:
		print(e)
		return False

def process_ai_review(pr_id, head_hash, base_hash):
	'''
	This will
		-Get the diff between the head and base commit
		-Get the review and suggestions from the open-ai
		-Then add the comments to the PR
	'''
	
	try:
  
		# dont run review if it was commit msg
		is_merge = is_merge_commit(head_hash)
  
		if is_merge:
			print("this is a merge commit so not proceeding further")
			return

		code_diff = get_pr_diff_bitbucket(head_hash=head_hash, base_hash=base_hash)
		code_diff_json_encoded = json.dumps(code_diff)
		prompt = get_prompt_bitbucket(code_diff_json_encoded)
		ai_review_suggestions = get_suggestions_from_openAi(prompt)
		add_comments_to_pr_bitbucket(pr_id, ai_review_suggestions)
	except Exception as e:
		print("xxxxxxxxxxxxxxxxxxxxx")
		print('-----------ERROR--------')
		print(f"❌ Error in AI review for PR {pr_id}: {e}")
		print("xxxxxxxxxxxxxxxxxxxxx")
 
 
@app.post("/webhook/bitbucket")
async def bitbucket_webhook(request: Request, background_tasks: BackgroundTasks):
	'''
	This is the main API function will get called for each callback
		-All the process will start from here.
	'''
	
	global commit_id, pr_number, repository_name, owner

	# Headers
	headers = dict(request.headers)
	x_bitbucket_event = headers['x-event-key']
	x_hub_signature_256 = headers['x-hub-signature-256']
	body_json = None

	# Body
	try:
		body_bytes = await request.body()
		body = await request.body()
		body_str = body_bytes.decode("utf-8")
		# print("Raw Body:", body_str)

		try:
			body_json = json.loads(body_str)
		except Exception:
			pass
	except Exception as e:
		print("Error reading body:", e)

	# ✅ Verify GitHub signature
	bitbucket_secret = os.environ.get('BITBUCKET_SECRET')

	if bitbucket_secret:
		# Convert secret to bytes
		secret_bytes = bitbucket_secret.encode("utf-8")

		signature = "sha256=" + hmac.new(secret_bytes, body, hashlib.sha256).hexdigest()
		if not hmac.compare_digest(signature, x_hub_signature_256):
			return {"status": "invalid signature"}

	print("----------------------------signature verified successfully--------------------------")

	payload = body_json
 
	if payload is None:
		return

	pull_request = payload['pullrequest']
	pr_id = pull_request['id']
	head_hash = pull_request['source']['commit']['hash']
	base_hash = pull_request['destination']['commit']['hash']
 
	print("-----------------------------------------")
	print(f'x_bitbucket_event = {x_bitbucket_event}')
 
	if x_bitbucket_event == 'pullrequest:created':
		redis_conn.set(f"bitbucket_pr_id:{pr_id}:head", head_hash)

	elif x_bitbucket_event == 'pullrequest:updated':
		old_head = redis_conn.get(f"bitbucket_pr_id:{pr_id}:head")
		if old_head != head_hash:
			redis_conn.set(f"bitbucket_pr_id:{pr_id}:head", head_hash)
			base_hash = old_head
	
		elif old_head == head_hash:
			print("xxxxxxxxxxxxxxxxxxxxxx[old_head = head_hash]xxxxxxxxxxxxxxx")
			# this could due to metadata changes like add commit, approve pr etc.
			pass

	
	background_tasks.add_task(process_ai_review, pr_id, head_hash, base_hash)
 
	return {"status": "ok"}


def main():
	uvicorn.run(app, host="0.0.0.0", port=8200)	


if __name__ == "__main__":
	main()
