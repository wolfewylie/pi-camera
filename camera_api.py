#coding=utf8
from __future__ import print_function
from flask import Flask, render_template, Response
from flask_cors import CORS
import time
import os 
import io
import httplib2
import datetime
from apiclient import discovery
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
import socket
import RPi.GPIO as GPIO
import picamera
import threading
import Adafruit_DHT
import json

try:
    from greenlet import getcurrent as get_ident
except ImportError:
    try:
        from thread import get_ident
    except ImportError:
        from _thread import get_ident

try:
	import argparse
	flags = argparse.ArgumentParser(parents=[tools.argparser]).parse_args()
except ImportError:
	flags = None

SCOPES = 'https://www.googleapis.com/auth/drive'
CLIENT_SECRET_FILE = ''
APPLICATION_NAME = ''
API_KEY = ''

check_for_errors = False

#Most of this code via: https://github.com/miguelgrinberg/flask-video-streaming
#Rest is a google sheets hack and then some temperature from code: https://www.terminalbytes.com/temperature-using-raspberry-pi-grafana/

# Raspberry Pi camera module (requires picamera package)
# from camera_pi import Camera

class CameraEvent(object):
    """An Event-like class that signals all active clients when a new frame is
    available.
    """
    def __init__(self):
        self.events = {}

    def wait(self):
        """Invoked from each client's thread to wait for the next frame."""
        ident = get_ident()
        if ident not in self.events:
            # this is a new client
            # add an entry for it in the self.events dict
            # each entry has two elements, a threading.Event() and a timestamp
            self.events[ident] = [threading.Event(), time.time()]
        return self.events[ident][0].wait()

    def set(self):
        """Invoked by the camera thread when a new frame is available."""
        now = time.time()
        remove = None
        for ident, event in self.events.items():
            if not event[0].isSet():
                # if this client's event is not set, then set it
                # also update the last set timestamp to now
                event[0].set()
                event[1] = now
            else:
                # if the client's event is already set, it means the client
                # did not process a previous frame
                # if the event stays set for more than 5 seconds, then assume
                # the client is gone and remove it
                if now - event[1] > 5:
                    remove = ident
        if remove:
            del self.events[remove]

    def clear(self):
        """Invoked from each client's thread after a frame was processed."""
        self.events[get_ident()][0].clear()


class BaseCamera(object):
    thread = None  # background thread that reads frames from camera
    frame = None  # current frame is stored here by background thread
    last_access = 0  # time of last client access to the camera
    event = CameraEvent()

    def __init__(self):
        """Start the background camera thread if it isn't running yet."""
        if BaseCamera.thread is None:
            BaseCamera.last_access = time.time()

            # start background frame thread
            BaseCamera.thread = threading.Thread(target=self._thread)
            BaseCamera.thread.start()

            # wait until frames are available
            while self.get_frame() is None:
                time.sleep(0)

    def get_frame(self):
        """Return the current camera frame."""
        BaseCamera.last_access = time.time()

        # wait for a signal from the camera thread
        BaseCamera.event.wait()
        BaseCamera.event.clear()

        return BaseCamera.frame

    @staticmethod
    def frames():
        """"Generator that returns frames from the camera."""
        raise RuntimeError('Must be implemented by subclasses.')

    @classmethod
    def _thread(cls):
        """Camera background thread."""
        # print('Starting camera thread.')
        frames_iterator = cls.frames()
        for frame in frames_iterator:
            BaseCamera.frame = frame
            BaseCamera.event.set()  # send signal to clients
            time.sleep(0)

            # if there hasn't been any clients asking for frames in
            # the last 20 seconds then stop the thread
            if time.time() - BaseCamera.last_access > 20:
                frames_iterator.close()
                # GPIO.output(PWR, False)
                # GPIO.cleanup()
                break
                # print('Stopping camera thread due to inactivity.')
        BaseCamera.thread = None
        
class Camera(BaseCamera):
    @staticmethod
    def frames():
        with picamera.PiCamera() as camera:
            # camera.awb_mode = 'off'
            # camera.awb_gains = (1,1)
            camera.saturation = -90
            # let camera warm up
            # GPIO.setmode(GPIO.BCM)
            # PWR = 14
            # GPIO.setwarnings(False)
            # GPIO.setup(PWR, GPIO.OUT)
            # GPIO.output(PWR, True)

            time.sleep(3)

            stream = io.BytesIO()
            for _ in camera.capture_continuous(stream, 'jpeg',
                                                 use_video_port=True):
                # return current frame
                stream.seek(0)
                yield stream.read()

                # reset stream for next frame
                stream.seek(0)
                stream.truncate()


app = Flask(__name__)
CORS(app)

@app.route('/')
def hello_world():
    return render_template('index.html')

def gen(camera):
    """Video streaming generator function."""
    while True:
        frame = camera.get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    """Video streaming route. Put this in the src attribute of an img tag."""
    return Response(gen(Camera()),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/temp')
def get_temp_humid():
    sensor = Adafruit_DHT.DHT22
    pin = 4
    humidity, temperature = Adafruit_DHT.read_retry(sensor, pin)
    data_return = {}
    data_return['temperature'] = round(temperature, 2)
    data_return['humidity'] = round(humidity, 2)
    response = app.response_class(
        response=json.dumps(data_return),
        status=200,
        mimetype='application/json'
    )
    print(response)
    return response

# --------------------------------------------------------------------------------------- #
# Code to set up Google Spreadsheet access *formatting is weird but necessary???*
# --------------------------------------------------------------------------------------- #
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

def write_to_spreadsheet(myIPaddress):
	scanTime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
	# file('TEST_FILE.txt','a')
	credentials = get_credentials()
	http = credentials.authorize(httplib2.Http())
	discoveryUrl = ('https://sheets.googleapis.com/$discovery/rest?'
					'version=v4')
	service = discovery.build('sheets', 'v4', http=http,
							  discoveryServiceUrl=discoveryUrl)
	spreadsheetId = '' 
	rangeName = 'Sheet1!A:B'
	result = service.spreadsheets().values().get(
		spreadsheetId=spreadsheetId, range=rangeName).execute()
	values = result.get('values', [])
	value_input_option = 'RAW'
	# ------------------------------------------------------------------------------------
	# Write to the Google Spreadsheet
	# ------------------------------------------------------------------------------------
	# s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	# s.connect(("8.8.8.8", 80))
	# myIPaddress = s.getsockname()[0]
	# s.close()

	messageToSend = "Camera local link is: " + str(myIPaddress) + "/cam/index.html"
	row = [myIPaddress, messageToSend]
	values = [ row ]
	# print(values)
	body = { 'values': values }
	result = service.spreadsheets().values().append(
		spreadsheetId=spreadsheetId, range=rangeName,
		valueInputOption=value_input_option, body=body, key=API_KEY).execute();

	# print(str(scanTime) + ': write to the Google Spreadsheet')

if __name__ == '__main__':

	internetConnected = False

	while internetConnected is False:
		try:
			s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			s.connect(("8.8.8.8", 80))
			myIPaddress = s.getsockname()[0]
			# print(myIPaddress)
			s.close()
			write_to_spreadsheet(myIPaddress)
			internetConnected = True
		except:
			time.sleep(5)

	HTML_FILE = open(os.path.join('/var/www/html/', 'cam/index.html'), 'w')
	HTML_FILE.write('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1 viewport-fit=cover"><meta name="apple-mobile-web-app-status-bar-style" content="black"><meta name="apple-mobile-web-app-capable" content="yes"><link rel="icon" type="image/png" href="baby.png"><link rel="apple-touch-icon" href="baby.png"><link rel="apple-touch-startup-image" href="baby.png"><title>Camera Test</title><link href="css/Merriweather.css" rel="stylesheet"><link href="css/styles.css" rel="stylesheet"></head><body><img id="camera_stream" src="http://' + myIPaddress + ':5000/video_feed"><div class="topCorner"><h2>Cam Title</h2><p class="temp"></p><p class="humid"></p></div><p class="time"></p><script src="js/app.js"></script></body></html>')

	HTML_FILE.close()

	JS_FILE = open(os.path.join('/var/www/html/', 'cam/js/app.js'), 'w')
	JS_FILE.write('var months = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];setInterval(function(){ 	var currentdate = new Date();	var hours = currentdate.getHours();	if (hours < 10) {		hours = "0" + hours;	}	var minutes = currentdate.getMinutes();	if (minutes < 10) {		minutes = "0" + minutes;	}	var seconds = currentdate.getSeconds();	if (seconds < 10) {		seconds = "0" + seconds;	}	var timeStamp = months[currentdate.getMonth()] + " " + currentdate.getDate() + ", " + currentdate.getFullYear() + " <br> " + hours + ":" + minutes + ":" + seconds;	document.querySelector("p.time").innerHTML = timeStamp;}, 1000);function updateTempHumid(jsonResponse) {	console.log(jsonResponse);	document.querySelector(".temp").innerHTML = jsonResponse.temperature.toFixed(2) + " °C";	document.querySelector(".humid").innerHTML = jsonResponse.humidity.toFixed(0) + "\% humidity";}fetch("http://' + myIPaddress + ':5000/temp")  .then(res => res.json())  .then(json => updateTempHumid(json));setInterval(function() {	fetch("http://' + myIPaddress + ':5000/temp")	  .then(res => res.json())	  .then(json => updateTempHumid(json));}, 100000)')
	JS_FILE.close()
	
	app.run(host=myIPaddress, threaded=True)
