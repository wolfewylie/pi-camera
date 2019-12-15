# pi-camera

 A Raspberry Pi camera implementation.

 This runs off two python scripts and an apache web server, currently running problem-free on a pi-zero-w.

 On startup, both scripts run themselves. The camera API script detects when the pi has connected to the internet and updates a Google Sheet with its IP address (useful on new networks where you don't have access to the router for DHCP reservations).
