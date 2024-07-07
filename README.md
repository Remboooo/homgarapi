HomGar API client library
=========================

[![PyPI version](https://badge.fury.io/py/homgarapi.svg)](https://badge.fury.io/py/homgarapi)

The purpose of this library is to programmatically control, and retrieve the layout and current values of devices 
in the HomGar app.

The current primary focus of this project is to retrieve sensor values of 
[RainPoint Smart+ devices](https://www.rainpointonline.com/collections/smart-garden)
so they can be integrated into HomeAssistant.

Current state of the project
----------------------------
Proof-of-concept: you can retrieve the layout of devices in your homes and their current values

Supported devices
-----------------
 * RainPoint Smart+ Irrigation Display Hub (HWS019WRF-V2)
 * RainPoint Smart+ 2-Zone Water Timer (HTV213FRF)
 * RainPoint Smart+ Soil&Moisture Sensor (HCS021FRF)
 * RainPoint Smart+ High Precision Rain Sensor (HCS012ARF)
 * RainPoint Smart+ Outdoor Air Humidity Sensor (HCS014ARF)

How to use
----------
This library is not meant to be used by itself; rather it is meant to be integrated in projects like HomeAssistant. 

However, if you really want to, you *can* run it commandline to see that it works. To do so:
1. Install:
```
pip install homgarapi
```
2. Create a file `config.yml` containing:  
```yaml
email: "<your HomGar login address>"
password: "<your HomGar password>"
```
3. Run it:
```
python -m homgarapi config.yml
```

This commandline tool will cache your access token in a file `cache.pickle` in a platform-specific user cache directory.

Caveats
-------
Logging in via this API will log you out in the app. It is advisable to create a separate API account from the app:
1. Log out from your main account
2. Create a new account
3. Log out and back into your main account
4. Invite your new account from 'Me' → 'Home management' → your home → 'Members'
5. Log out and back into your new account
6. Accept the invite

To-do
-----
1. Support token renewal such that we don't have to store the password. I haven't been able to trigger token renewal in the app so I can sniff which endpoint it uses.
2. Create a HomeAssistant integration that uses this library
3. Support all RainPoint Smart+ devices. I only have a select few to test with (see "Supported devices").
4. Investigate the meaning of currently unknown status values
5. Add support for controlling devices via the API
