import requests, json, arrow, hashlib, urllib, datetime
from secret import USERNAME, PASSWORD, NS_URL, NS_SECRET

# this is the enteredBy field saved to Nightscout
NS_AUTHOR = "Diabetes-M (dm2nsc)"
TIMEZONE = "Europe/Berlin"
DO_MYSUGR_PROCESSING = (USERNAME == 'jwoglom')

def get_login():
	return requests.post('https://analytics.diabetes-m.com/api/v1/user/authentication/login', json={
		'username': USERNAME,
		'password': PASSWORD,
		'device': ''
	}, headers={
		'origin': 'https://analytics.diabetes-m.com'
	})


def get_entries(login):
	auth_code = login.json()['token']
	print("Loading entries...")
	entries = requests.post('https://analytics.diabetes-m.com/api/v1/diary/entries/list', 
		cookies=login.cookies, 
		headers={
			'origin': 'https://analytics.diabetes-m.com',
			'authorization': 'Bearer '+auth_code
		}, json={
			'fromDate': -1,
			'toDate': -1,
			'page_count': 90000,
			'page_start_entry_time': 0
		})
	return entries.json()


def to_mgdl(mmol):
	return round(mmol*18)

def convert_nightscout(entries, start_time=None):
	out = []
	for entry in entries:
		bolus = entry["carb_bolus"] + entry["correction_bolus"]
		try:
			time = arrow.get(int(entry["entry_time"])/1000).to(entry["timezone"])
		except:
			time = arrow.get(int(entry["last_modified"])/1000).to(entry["timezone"])
		try:
			notes = entry["notes"]
		except:
			notes = ""

		if start_time and start_time >= time:
			continue

		author = NS_AUTHOR
		created_at = time.format('YYYY-MM-DDTHH:mm:ssZ')

		# You can do some custom processing here, if necessary. e.x.:
		if entry["basal"]:
			basal = entry["basal"]
			duration_h = 24
			duration_min = duration_h * 60
			reason = "Lantus"
			
			if entry["basal_insulin_type"]==6: #Abasaglar
				duration_h = 22
				duration_min = duration_h * 60
				reason="Abasaglar"
			if entry["basal_insulin_type"]==32: #Toujeo
				duration_h = 28
				duration_min = duration_h * 60
				reason="Toujeo"
			notes = str(basal) + "U/" + str(duration_min) + "min, " + notes
			if duration_h > 24:
				duration_h = 24
			basal_rate = float(basal)/duration_h
			out.append({
				"eventType": "Temp Basal",
				"created_at": created_at,
				"absolute": basal_rate,
				#"basal" : basal_rate,
				"notes": notes,
				"enteredBy": author,
				"duration": duration_min,
				"reason": reason,
				"notes": notes,
				"basal_insulin": basal
			})
		
		dat = {
			"eventType": "Meal Bolus",
			"created_at": created_at,
			"carbs": entry["carbs"],
			"insulin": bolus,
			"notes": notes,
			"enteredBy": author
		}
		if entry["glucose"]:
			glucose = entry["glucoseInCurrentUnit"] if entry["glucoseInCurrentUnit"] and entry["us_units"] else to_mgdl(entry["glucose"])
			dat.update({
				"eventType": "BG Check",
				"glucose": glucose,
				"glucoseType": "Finger",
				"units": "mg/dL"
			})
		elif entry["category"] == 14:
    		# Diabetes:M GoogleFit Sync -> this entry is an exercise from GoogleFit
			print("is exercise: ", entry["exercise_comment"], ",  duration: ", entry["exercise_duration"]  )
			continue

		out.append(dat)

	return out

def upload_nightscout(ns_format):
	out = []
	for ns in ns_format:
		out.append(ns)
		if(len(out)>100):
			upload = upload_ns(out)
			out = []
	upload = upload_ns(out)

def upload_ns(ns_format):
	upload = requests.post(NS_URL + 'api/v1/treatments?api_secret=' + NS_SECRET, json=ns_format, headers={
		'Accept': 'application/json',
		'Content-Type': 'application/json',
		'api-secret': hashlib.sha1(NS_SECRET.encode()).hexdigest()
	})
	print("Nightscout upload status:", upload.status_code, upload.text)
	return upload

def get_last_nightscout():
	# last = requests.get(NS_URL + 'api/v1/treatments?count=1&find[enteredBy]='+urllib.parse.quote(NS_AUTHOR) )
	last = requests.get(NS_URL + 'api/v1/treatments?count=1&find[enteredBy]='+urllib.parse.quote(NS_AUTHOR), headers={
		'Accept': 'application/json',
		'Content-Type': 'application/json',
		'api-secret': hashlib.sha1(NS_SECRET.encode()).hexdigest()
	})
	# print(NS_URL , 'api/v1/treatments?count=1&find[enteredBy]=',urllib.parse.quote(NS_AUTHOR))
	if last.status_code == 200:
		js = last.json()
		if len(js) > 0:
			return arrow.get(js[0]['created_at']).datetime

def main():
	print("Logging in to Diabetes-M...", datetime.datetime.now())
	login = get_login()
	if login.status_code == 200:
		entries = get_entries(login)
	else:
		print("Error logging in to Diabetes-M: ",login.status_code, login.text)
		exit(0)

	print("Loaded", len(entries["logEntryList"]), "entries")

	# skip uploading entries past the last entry
	# uploaded to Nightscout by `NS_AUTHOR`
	ns_last = get_last_nightscout()
	print("Last nightscout data is from ",ns_last)

	ns_format = convert_nightscout(entries["logEntryList"], ns_last)

	print("Converted", len(ns_format), "entries to Nightscout format")
	# print(ns_format)

	print("Uploading", len(ns_format), "entries to Nightscout...")
	upload_nightscout(ns_format)


if __name__ == '__main__':
	main()
