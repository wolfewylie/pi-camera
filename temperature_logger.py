from __future__ import print_function
import time
import threading
import datetime
import os
from apiclient import discovery
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
import socket
import httplib2
import Adafruit_DHT
import re

SCOPES = 'https://www.googleapis.com/auth/drive'
CLIENT_SECRET_FILE = ''
APPLICATION_NAME = ''
API_KEY = ''

# This class largely via: https://stackoverflow.com/questions/474528/what-is-the-best-way-to-repeatedly-execute-a-function-every-x-seconds-in-python

class RepeatedTimer(object):
	def __init__(self, interval, function, *args, **kwargs):
		self._timer = None
		self.interval = interval
		self.function = function
		self.args = args
		self.kwargs = kwargs
		self.is_running = False
		self.next_call = time.time()
		self.start()

	def _run(self):
		self.is_running = False
		self.start()
		self.function(*self.args, **self.kwargs)

	def start(self):
		if not self.is_running:
			self.next_call += self.interval
			self._timer = threading.Timer(self.next_call - time.time(), self._run)
			self._timer.start()
			self.is_running = True

	def stop(self):
		self._timer.cancel()
		self.is_running = False

def get_credentials():
	# Gets valid user credentials from storage.
	home_dir = os.path.expanduser('~')
	credential_dir = os.path.join('/home/pi/', '.credentials')
	if not os.path.exists(credential_dir):
		os.makedirs(credential_dir)
	credential_path = os.path.join(credential_dir,
								   'sheets.googleapis.com-python-quickstart.json')

	store = Storage(credential_path)
	credentials = store.get()
	if not credentials or credentials.invalid:
		flow = client.flow_from_clientsecrets(CLIENT_SECRET_FILE, SCOPES)
		flow.user_agent = APPLICATION_NAME
		if flags:
			credentials = tools.run_flow(flow, store, flags)
		else: # Needed only for compatibility with Python 2.6
			credentials = tools.run(flow, store)
		print('Storing credentials to ' + credential_path)
	return credentials

def logTempHumid():
	scanTime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	# file('TEST_FILE.txt','a')
	scanTime = re.sub("'", "", scanTime)
	http = credentials.authorize(httplib2.Http())
	discoveryUrl = ('https://sheets.googleapis.com/$discovery/rest?'
					'version=v4')
	service = discovery.build('sheets', 'v4', http=http,
							  discoveryServiceUrl=discoveryUrl)
	spreadsheetId = '' 
	rangeName = 'Sheet1!A:C'

	value_input_option = 'USER_ENTERED'

	temperature = ''
	humidity = ''

	while temperature == '' and humidity == '':
		sensor = Adafruit_DHT.DHT22
		pin = 4
		humidity, temperature = Adafruit_DHT.read_retry(sensor, pin)
		if temperature == '' or humidity == '':
			time.sleep(15)

	row = [scanTime, temperature, humidity]
	# print(row)
	values = [ row ]
	# print(values)
	body = { 'values': values }
	result = service.spreadsheets().values().append(
		spreadsheetId=spreadsheetId, range=rangeName,
		valueInputOption=value_input_option, body=body, key=API_KEY).execute();

def startTempLogging():
	# print("starting...")
	rt = RepeatedTimer(300, logTempHumid) # it auto-starts, no need of rt.start()
	try:
		logTempHumid()
		time.sleep(5)
	finally:
		rt.start() # better in a try/finally block to make sure the program ends!

credentials = get_credentials()

startTempLogging()
