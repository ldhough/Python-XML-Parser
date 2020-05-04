#Lannie Dalton Hough
#email me at ldhough@stetson.edu or ldhough2000@gmail.com if this stops working

import urllib.request
import xml.etree.ElementTree as ET
import re
import json
import requests
import firebase
import firebase_admin
from firebase_admin import credentials, firestore, storage, db
import datetime

print("Script starting.")

#Fetch service account key JSON file contents
cred = credentials.Certificate('./stetson-events-firebase-adminsdk-swmox-5af9d436a7.json')
#Initialize app with a service account granting admin privileges
default_app = firebase_admin.initialize_app(cred, {'databaseURL': 'https://stetson-events.firebaseio.com'})

#EventInstance, EventType, & Location are used to represent events
class EventInstance:
    def __init__(self):
        self.guid = ""
        self.name = ""
        self.time = ""
        self.endTime = ""
        self.date = ""
        self.endDate = ""
        self.url = ""
        self.summary = ""
        self.description = ""
        self.contactName = ""
        self.contactPhone = ""
        self.contactMail = ""
        self.mainLocation = ""
        self.mainEventType = ""
        self.mainAddress = ""
        self.mainCity = ""
        self.mainState = ""
        self.mainZip = ""
        self.mainLat = ""
        self.mainLon = ""
        self.subLocations = []
        self.hasCultural = False
        self.eventTypes = []
        self.daysIntoYear = 0 #for Firebase querying on iOS side
        self.numberAttending = 0

class EventType:
    def __init__(self):
        self.eventID = ""
        self.eventTypeName = ""

#not all properties used or written to FB
class Location:
    def __init__(self):
        self.name = ""
        self.facilityID = ""
        self.address = ""
        self.city = ""
        self.state = ""
        self.zip = ""
        self.lat = 0.0
        self.lon = 0.0

daysInMonths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
currentDateTime = datetime.datetime.now()
if currentDateTime.year % 4 == 0: #check if it is a leap year
    daysInMonths[1] = 29

#function returns the number of days into a year a date is, formatted as 3/14/2000
def daysIntoYear(date):
    dateSplit = date.split("/")
    daysIntoYear = 0
    i = 1
    while i < int(dateSplit[0]): #add number of days from past months
        daysIntoYear += daysInMonths[i-1]
        i += 1
    daysIntoYear += int(dateSplit[1]) #add number of days into current month the event is
    return daysIntoYear

def parseEventAssociationHTML():
    """
    The regex matches any text (including newlines) on the page source starting with 
    '(<div id="core_search")' and ending with '<\/select><a href='.  The text contained 
    within this block has all the information about event types and subtypes.
    """
    eventTypeGroupRegex = r'(<div id="core_search")(?:.|\n)+?(?=<\/select><a href=)'
    eventTypeGroupPattern = re.compile(eventTypeGroupRegex)
    page = urllib.request.urlopen("https://calendar.stetson.edu/site/deland/").read()
    matched = re.search(eventTypeGroupPattern, page.decode('utf-8'))
    matched = matched.group()
    return makeAssociationDic(matched)

def parseLocationAssociationHTML():
    #regex performs same function as one in parseEventAssociationHTML() but for location block in HTML
    eventLocationGroupRegex = r'(class="search-location core-dropdown">)(?:.|\n)+?(?=<\/select><a href=)'
    eventLocationGroupPattern = re.compile(eventLocationGroupRegex)
    page = urllib.request.urlopen("https://calendar.stetson.edu/site/deland/").read()
    matched = re.search(eventLocationGroupPattern, page.decode('utf-8'))
    matched = matched.group()
    return makeAssociationDic(matched)

def makeAssociationDic(s):
    """
    Structure for dictionary will be:
    {
        "Admissions": {
            "Admissions": "guid",
            "Graduate": "guid",
            "Undergraduate": "guid"
        }
    }
    """
    dictionary = {}
    lines = s.split('\n') #split on newlines
    #regex strips start of line with positive lookbehind on start & end of line with positive lookahead
    reduceLineRegex = r'(?<=option value=").+(?=<)'
    reduceLinePattern = re.compile(reduceLineRegex)
    reducedArray = []
    for line in lines:
        matched = re.search(reduceLinePattern, line)
        if matched != None:
            matched = matched.group()
            reducedArray.append(matched)
    key = "" #keys for main event or location types in dictionary
    for line in reducedArray:
        guidNameSplit = line.split('">') #split on "> to get array with guid and name
        guid = guidNameSplit[0]
        name = guidNameSplit[1]
        substring = '&#39;' #this HTML tag is invalid for FB key
        if substring in name: #replace invalid characters for FB keys
            name = name.replace(substring, "'") #replace with ', which HTML tag represents
        badCharacters = ['.', '$', '/', '[', ']', '#']
        for c in badCharacters:
            name = name.replace(c, "")
        if name[0] != '-':
            key = name
            dictionary[key] = {}
            dictionary[key][name] = guid
        else:
            dictionary[key][name] = guid
    #print(dictionary)
    return dictionary

def removeDashes(dic, locOrEType): #remove dashes before writing to Firebase
    dicWithoutDashes = {}
    subDic = {}
    for key, value in dic.items():
        for k, v in value.items():
            if k[0] == "-":
                k = k[1:]
            subDic[k] = v
        dicWithoutDashes[key] = subDic
        subDic = {}
    with open(locOrEType + 'Associations.json', 'w', encoding='utf8') as outfile:
        json.dump(dicWithoutDashes, outfile, ensure_ascii=False, indent=4)
    return dicWithoutDashes

def iterateDic(dictionary, checkValue, mainElement): #send "" for mainElement
    for key, value in dictionary.items():
        mainElement = key
        for k, v in value.items():
            if v == checkValue:
                return mainElement

#parses the XML of Stetson's event page to extract relevant information about events, returns event array
def parseXML(locDic, eventDic):
    url = 'https://calendar.stetson.edu/site/deland/page/xml/?duration=100days'
    documentXML = urllib.request.urlopen(url).read()
    root = ET.fromstring(documentXML)
    eventList = []
    for child in root: #reads elements under <events> tag
        foundMainLocation = False #these tags make sure the most relevant information is extracted for primary location & event type display
        foundMainEventType = False
        foundMainAddress = False
        foundMainCity = False
        foundMainState = False
        foundMainZip = False
        foundMainLat = False
        foundMainLon = False
        if child.tag == 'event':
            event = child
            newEvent = EventInstance()
            for eventAttribute in event: #reads event elements under <events> tag
                if eventAttribute.tag == 'id':
                    newEvent.guid = eventAttribute.text
                    #print(newEvent.guid)
                elif eventAttribute.tag == "name":
                    newEvent.name = eventAttribute.text
                elif eventAttribute.tag == "local-start-date":
                    newEvent.date = eventAttribute.text
                    newEvent.daysIntoYear = daysIntoYear(newEvent.date)
                elif eventAttribute.tag == "local-end-date":
                    newEvent.endDate = eventAttribute.text
                elif eventAttribute.tag == "local-start-time":
                    newEvent.time = eventAttribute.text
                elif eventAttribute.tag == "local-end-time":
                    newEvent.endTime = eventAttribute.text
                elif eventAttribute.tag == "url":
                    newEvent.url = eventAttribute.text
                elif eventAttribute.tag == "summary":
                    newEvent.summary = eventAttribute.text
                elif eventAttribute.tag == "description":
                    newEvent.description = eventAttribute.text
                elif eventAttribute.tag == "contact":
                    contact = eventAttribute
                    for contactInfo in contact: #dives into block under <contact> tag
                        if contactInfo.tag == "name":
                            newEvent.contactName = contactInfo.text
                        elif contactInfo.tag == "phone":
                            newEvent.contactPhone = contactInfo.text
                        elif contactInfo.tag == "email":
                            newEvent.contactMail = contactInfo.text
                elif eventAttribute.tag == "locations":
                    locationList = eventAttribute
                    for locationInstance in locationList: #dives into block under <locations> tag
                        location = locationInstance
                        newLocation = Location()
                        saveGUID = ""
                        for locationElement in location: #for each tag in each location
                            if locationElement.tag == "facility-id":
                                newLocation.facilityID = locationElement.text
                                saveGUID = locationElement.text.replace("-", "")
                                if foundMainLocation == False:
                                    newEvent.mainLocation = iterateDic(locDic, locationElement.text.replace("-", ""), "") #assigning main event location
                                    foundMainLocation = True
                                    firstLoc = Location()
                                    firstLoc.name = newEvent.mainLocation
                                    newEvent.subLocations.append(firstLoc)
                            elif locationElement.tag == "name":
                                newLocation.name = locationElement.text
                                if foundMainLocation == True:
                                    checkNewMainLoc = iterateDic(locDic, saveGUID, "")
                                    if checkNewMainLoc != newEvent.mainLocation:
                                        extraLoc = Location()
                                        extraLoc.name = checkNewMainLoc
                                        newEvent.subLocations.append(extraLoc)
                            elif locationElement.tag == "address1":
                                newLocation.address = locationElement.text
                                if foundMainAddress == False:
                                    newEvent.mainAddress = locationElement.text
                                    foundMainAddress = True
                            elif locationElement.tag == "city":
                                newLocation.city = locationElement.text
                                if foundMainCity == False:
                                    newEvent.mainCity = locationElement.text
                                    foundMainCity = True
                            elif locationElement.tag == "state":
                                newLocation.state = locationElement.text
                                if foundMainState == False:
                                    newEvent.mainState = locationElement.text
                                    foundMainState = True
                            elif locationElement.tag == "zipcode":
                                newLocation.zip = locationElement.text
                                if foundMainZip == False:
                                    newEvent.mainZip = locationElement.text
                                    foundMainZip = True
                            elif locationElement.tag == "latitude":
                                newLocation.lat = locationElement.text
                                if foundMainLat == False:
                                    newEvent.mainLat = locationElement.text
                                    foundMainLat = True
                            elif locationElement.tag == "longitude":
                                newLocation.lon = locationElement.text
                                if foundMainLon == False:
                                    newEvent.mainLon = locationElement.text
                                    foundMainLon = True
                        if newLocation.name != newEvent.mainLocation: #prevents double locations from being written to JSON
                            newEvent.subLocations.append(newLocation)
                elif eventAttribute.tag == "categories":
                    categoryList = eventAttribute
                    for categoryInstance in categoryList: #each individual category starts here
                        category = categoryInstance
                        newCategory = EventType()
                        saveCatGUID = ""
                        for categoryElement in category: #each element in each category starts here
                            if categoryElement.tag == "id":
                                newCategory.eventID = categoryElement.text
                                saveCatGUID = categoryElement.text
                                if foundMainEventType == False:
                                    newEvent.mainEventType = iterateDic(eventDic, categoryElement.text.replace("-", ""), "") #assigning main event type
                                    foundMainEventType = True
                                    firstEType = Location()
                                    firstEType.eventTypeName = newEvent.mainEventType
                                    newEvent.eventTypes.append(firstEType)
                            if categoryElement.tag == "name":
                                if categoryElement.text == "Cultural Credits":
                                    newEvent.hasCultural = True
                                newCategory.eventTypeName = categoryElement.text
                                if foundMainEventType == True:
                                    checkNewMain = iterateDic(eventDic, saveCatGUID, "")
                                    if checkNewMain != newEvent.mainEventType:
                                        extraCategory = EventType()
                                        extraCategory.name = checkNewMain
                                        extraCategory.guid = "12345"
                                        newEvent.eventTypes.append(extraCategory)
                        if newCategory.eventTypeName != newEvent.mainEventType: #prevents double locations from being written to JSON
                            newEvent.eventTypes.append(newCategory)
            if newEvent.mainLat != "" and newEvent.mainLat != None:
                if float(newEvent.mainLat) < 0.0: #lat should be positive for DeLand, if negative the user input lat/lon backwards
                    tempLon = newEvent.mainLat
                    tempLat = newEvent.mainLon
                    newEvent.mainLat = tempLat
                    newEvent.mainLon = tempLon
            substringOne = "Cancelled"
            substringTwo = "cancelled"
            substringThree = "Tutoring"
            substringFour = "tutoring"
            if newEvent.name.find(substringOne) == -1 and newEvent.name.find(substringTwo) == -1 and newEvent.name.find(substringThree) == -1 and newEvent.name.find(substringFour) == -1:
                eventList.append(newEvent)
    return eventList

#Format event list as dictionary & location list for writing to FB
#Using ternary operator as pseudo-optionals
def formatEvents(eventList):
    data = {}
    data["eventList"] = {}
    locArr = [] #for location data on FB
    absolutePosition = 0
    for event in eventList:
        newEvent = {}
        newEvent["absolutePosition"] = absolutePosition #index in the list
        absolutePosition += 1
        newEvent["guid"] = event.guid if event.guid != None else ""
        newEvent["name"] = event.name if event.name != None else ""
        newEvent["time"] = event.time if event.time != None else ""
        newEvent["endTime"] = event.endTime if event.endTime != None else ""
        newEvent["endDate"] = event.endDate if event.endDate != None else ""
        newEvent["date"] = event.date if event.date != None else ""
        newEvent["daysIntoYear"] = event.daysIntoYear if event.daysIntoYear != None else 0
        newEvent["url"] = event.url if event.url != None else ""
        newEvent["summary"] = event.summary if event.summary != None else ""
        newEvent["description"] = event.description if event.description != None else ""
        newEvent["contactName"] = event.contactName if event.contactName != None else ""
        newEvent["contactPhone"] = event.contactPhone if event.contactPhone != None else ""
        newEvent["contactMail"] = event.contactMail if event.contactMail != None else ""
        newEvent["numberAttending"] = 0
        newEvent["mainLocation"] = event.mainLocation if event.mainLocation != None else ""
        if event.mainEventType != None: #conflicts sometimes occur when event type & location are the same, causing mainEventType to be None/null/nil.  this ensures there is a main event type
            newEvent["mainEventType"] = event.mainEventType if event.mainEventType != None else ""
        else:
            i = 0
            found = False
            while found == False:
                while event.eventTypes[i].eventTypeName == None:
                    i += 1
                newEvent["mainEventType"] = event.eventTypes[i].eventTypeName
                found = True
        newEvent["address"] = event.mainAddress if event.mainAddress != None else ""
        newEvent["city"] = event.mainCity if event.mainCity != None else ""
        newEvent["state"] = event.mainState if event.mainState != None else ""
        newEvent["zip"] = event.mainZip if event.mainZip != None else ""
        newEvent["lat"] = event.mainLat if event.mainLat != None else ""
        newEvent["lon"] = event.mainLon if event.mainLon != None else ""
        newEvent["hasCultural"] = event.hasCultural if event.hasCultural != None else False
        newEvent["subLocations"] = []
        for location in event.subLocations:
            newEvent["subLocations"].append(location.name)
        newEvent["eventTypes"] = []
        for ev in event.eventTypes:
            if (ev.eventTypeName != "") & (ev.eventTypeName != None): #hacky workaround but sometimes "" or None gets put in this array.  didn't feel like finding the bug, written JSON is correct
                newEvent["eventTypes"].append((ev.eventTypeName))
        data["eventList"][event.guid] = newEvent
        #
        newELocDic = {}
        newELocDic["guid"] = event.guid
        newELocDic["daysIntoYear"] = event.daysIntoYear
        locArr.append(newELocDic)
        #
        with open('EventInformation.json', 'w', encoding='utf-8') as outfile:
            json.dump(data, outfile, ensure_ascii=False, indent=4)
    return (data, locArr)


#Initiate parsing
eventAssocationDic = parseEventAssociationHTML() #separate associations for events & locations for better search functionality client-side
locAssociationDic = parseLocationAssociationHTML() #& a more robust Firebase Database architecture

eventList = parseXML(locAssociationDic, eventAssocationDic)
tup = formatEvents(eventList)
eventDic = tup[0] #to write to FB for events, tup[0] is dictionary from return
eventLocList = tup[1] #tup[1] is events in order

eListRef = db.reference('Test/eventList')
didGet = False
try:
    oldEventData = eListRef.get()
    didGet = True
except:
    print("Couldn't get old events.")

if didGet: #sets correct value for numberAttending by querying old data
    for k, v in oldEventData.items():
        numAttending = v['numberAttending']
        try:
            eventDic['eventList'][k]['numberAttending'] = numAttending
        except:
            print("Keyerror, expected & ignore.")

eventAssocationDic = removeDashes(eventAssocationDic, "EventType") #remove dashes from keys before writing to FB
locAssociationDic = removeDashes(locAssociationDic, "Location")

eRef = db.reference('Test/test')
eListLocsRef = db.reference('/eLocsTest')
eventAssociationsRef = db.reference('/EventTypeAssociationsTest')
locationAssociationsRef = db.reference('/LocationAssociationsTest')

try:
    eRef.delete()
except:
    print("Couldn't delete events from DB or couldn't find in DB...")
try:
    eventAssociationsRef.delete()
except:
    print("Couldn't delete event type associations from DB or couldn't find in DB...")
try:
    locationAssociationsRef.delete()
except:
    print("Couldn't delete location associations from DB or couldn't find in DB...")
try:
    eListLocsRef.delete()
except:
    print("Couldn't delete event order list from DB or couldn't find in DB...")

eRef = db.reference('Test')
eRef.set(eventDic)
eListLocsRef.set(eventLocList)
eventAssociationsRef.set(eventAssocationDic)
#print(locAssociationDic)
locationAssociationsRef.set(locAssociationDic)

print("Script ended.")