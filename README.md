# GOOSE Scope

This is a tool to visualise GOOSE messages on a process bus in real time. This application will analyse an interface, and visualise GOOSE values(iec 61850 8-1) received on that interface in a list. Each entry in that list represents a stream. Click one or more entries to subscribe to those streams
and display the values of that stream in the chart. The display is updated every 0.1 second.  

It will display values as they come in, and automatically scale the graph to accomodate the values.  

The scrol-wheel will zoom the graph. dragging the chart will allow to pan.  

![Alt text](goosescope.png?raw=true "Screenshot of the GOOSE Scope")


## Limitations
 - currently you cannot pause the chart  
 - only float/int/uint and boolean values are displayed, others such as bitstring are not  
 - only gocbref is used to filter out a stream. Therefore gocbref should be unique per GOOSE stream  
 - if streams with matching gocbref, but different appid, source or destination mac are detected, an error is shown in the log and the data will interfere with a stream that is being displayed in the graph.  


## Dependencies:
### Flask 1.0.2  
install with  
 `~$ pip install flask`  

### libiec61850 1.4.2  
install with  
    `~$ git clone https://github.com/mz-automation/libiec61850/tree/v1.4.2 && cd libiec61850 && make dynlib && sudo make install`  
NOTE: libiec61850.so.1.4.2 is assumed to be installed in $PATH, if the above command does not install in a location included in $PATH, add it manually


## Run:  
from the folder where you cloned the repo  
`$ sudo ./goosescope [interface]`  

or build and install with:  
`$ python setup.py build && sudo python setup.py install`

and run from any location  
`~$ sudo goosescope [interface]`  

Browse to http://127.0.0.1:5000  
