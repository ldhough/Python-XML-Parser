#!/usr/bin/env/python3.8

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

print("Script starting")

#Fetch service account key JSON file contents
cred = credentials.Certificate('./stetson-events-firebase-adminsdk-swmox-5af9d436a7.json')
#Initialize app with a service account granting admin privileges
default_app = firebase_admin.initialize_app(cred, {'databaseURL': 'https://stetson-events.firebaseio.com'})
#firebase_admin.initialize_app(cred, {'storageBucket': 'stetson-events.appspot.com'}) #was using to write files
#bucket = storage.bucket() #was using to write files

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
        self.hasAthletic = False
        self.eventTypes = []
        self.daysIntoYear = 0 #for Firebase querying on iOS side

class EventType:
    def __init__(self):
        self.eventID = ""
        self.eventTypeName = ""

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

class nameGUIDPair:
    def __init__(self):
        self.guid = ""
        self.name = ""

daysInMonths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
currentDateTime = datetime.datetime.now()
if currentDateTime.year % 4 == 0: #check if it is a leap year
    daysInMonths[1] = 29

def daysIntoYear(date):
    dateSplit = date.split("/")
    daysIntoYear = 0
    i = 1
    while i < int(dateSplit[0]): #add number of days from past months
        daysIntoYear += daysInMonths[i-1]
        i += 1
    daysIntoYear += int(dateSplit[1]) #add number of days into current month the event is
    return daysIntoYear

eventAssocationDic = {} #separate associations for events & locations for better search functionality client-side
locAssociationDic = {} #& a more robust Firebase Database architecture

#parsing the HTML is necessary because the XML does not always correctly associate
#events with their primary location and event type
def parseHTML():
    regex = r'(<option\svalue=")(.+)' #strip out "<option value ... /option>" blocks
    pattern = re.compile(regex)
    pageLines = urllib.request.urlopen("https://calendar.stetson.edu/site/deland/").readlines()
    matchedLines = []
    for pageLine in pageLines:
        matched = re.search(pattern, pageLine.decode('utf-8'))
        if matched != None:
            matched = matched.group()
            #print(matched)
            matchedLines.append(matched)
    regexTwo = r'("|">)([^<]+)' #process HTML further
    regexNoQuotes = r'[^"]+'
    patternTwo = re.compile(regexTwo)
    patternNoQuotes = re.compile(regexNoQuotes)
    nameGUIDMatches = []
    for line in matchedLines:
        matched = re.search(patternTwo, line)
        if matched != None:
            matchedNameGUID = matched.group()
            splitNameGUID = matchedNameGUID.split(">")
            newNameGUIDPair = nameGUIDPair()
            newNameGUIDPair.name = splitNameGUID[1]
            guidNoQuotes = re.search(patternNoQuotes, splitNameGUID[0]).group()
            newNameGUIDPair.guid = guidNoQuotes
            nameGUIDMatches.append(newNameGUIDPair)
    #for pair in nameGUIDMatches:
        #print(pair.name)
    whatTypeDic = {}
    newSubTypeDic = {}
    reachedLocations = False #before this will append to event type association dic, after it will append to location association dic
    currentName = ""
    for pair in nameGUIDMatches:
        if currentName == "Allen Hall":#pair.name == "Allen Hall":
            reachedLocations = True
        if strContainChar(pair.name, "#"):
            #print("MADE IT HERE")
            try: #gets rid of an HTML format that is invalid for FB key
                pair.name = pair.name.replace("#", "'")
                pair.name = pair.name.replace("&", "")
                pair.name = pair.name.replace("3", "")
                pair.name = pair.name.replace("9", "")
                pair.name = pair.name.replace(";", "")
            except:
                pair.name = pair.name.replace("#", "")
        if strContainChar(pair.name, "."):
            pair.name = pair.name.replace(".", "")
        if strContainChar(pair.name, "$"):
            pair.name = pair.name.replace("$", "")
        if strContainChar(pair.name, "/"):
            pair.name = pair.name.replace("/", "")
        if strContainChar(pair.name, "["):
            pair.name = pair.name.replace("[", "")
        if strContainChar(pair.name, "]"):
            pair.name = pair.name.replace("]", "")
            #print(pair.name)



        if pair.name[0] != "-":
            if currentName != "":
                whatTypeDic[currentName] = newSubTypeDic
                if reachedLocations == False: #these two if statements populate different association dictionaries
                    #cN = currentName[1:]
                    #eventAssocationDic[cN] = newSubTypeDic
                    eventAssocationDic[currentName] = newSubTypeDic
                elif reachedLocations == True:
                    #cN = currentName[1:]
                    #locAssociationDic[cN] = newSubTypeDic
                    locAssociationDic[currentName] = newSubTypeDic
            currentName = pair.name
            newSubTypeDic = {}
            newSubTypeDic[pair.name] = pair.guid
        elif pair.name[0] == "-":
            keyWithoutDash = pair.name[1:]
            if keyWithoutDash == currentName: #if subtype name is also main type name
                newSubTypeDic[pair.name] = pair.guid #keep the '-' char to signify subtype
            else:
                newSubTypeDic[keyWithoutDash] = pair.guid
            #newSubTypeDic[pair.name] = pair.guid
        #print(pair.name, pair.guid)
    return whatTypeDic

def iterateDic(dictionary, checkValue, mainElement): #send "" for mainElement
    for key, value in dictionary.items():
        mainElement = key
        for k, v in value.items():
            if v == checkValue:
                return mainElement

def strContainChar(str, character): #used to filter for strings that contain #, which cannot be used as a FB key
    for c in str:
        if c == character:
            return True
    return False

#parses the XML of Stetson's event page to extract relevant information about events
def parseXML(typeDic):
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
                                    newEvent.mainLocation = iterateDic(typeDic, locationElement.text.replace("-", ""), "") #assigning main event location
                                    foundMainLocation = True
                                    firstLoc = Location()
                                    firstLoc.name = newEvent.mainLocation
                                    newEvent.subLocations.append(firstLoc)
                            elif locationElement.tag == "name":
                                newLocation.name = locationElement.text
                                if foundMainLocation == True:
                                    checkNewMainLoc = iterateDic(typeDic, saveGUID, "")
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
                                    newEvent.mainEventType = iterateDic(typeDic, categoryElement.text.replace("-", ""), "") #assigning main event type
                                    foundMainEventType = True
                                    firstEType = Location()
                                    firstEType.eventTypeName = newEvent.mainEventType
                                    newEvent.eventTypes.append(firstEType)
                            if categoryElement.tag == "name":
                                if categoryElement.text == "Cultural Credits":
                                    newEvent.hasCultural = True
                                newCategory.eventTypeName = categoryElement.text
                                if foundMainEventType == True:
                                    checkNewMain = iterateDic(typeDic, saveCatGUID, "")
                                    if checkNewMain != newEvent.mainEventType:
                                        extraCategory = EventType()
                                        extraCategory.name = checkNewMain
                                        extraCategory.guid = "12345"
                                        newEvent.eventTypes.append(extraCategory)
                        if newCategory.eventTypeName != newEvent.mainEventType: #prevents double locations from being written to JSON
                            newEvent.eventTypes.append(newCategory)
            if newEvent.mainLat != "":
                if float(newEvent.mainLat) < 0.0: #lat should be positive for DeLand, if negative the user input lat/lon backwards
                    tempLon = newEvent.mainLat
                    tempLat = newEvent.mainLon
                    newEvent.mainLat = tempLat
                    newEvent.mainLon = tempLon
            substringOne = "Cancelled"
            substringTwo = "cancelled"
            substringThree = "Tutoring"
            substringFour = "tutoring"
            #if substringOne in newEvent.name == False and substringTwo in newEvent.name == False and substringThree in newEvent.name == False and substringFour in newEvent.name == False:
            #if substringOne in newEvent.name == False:
            if newEvent.name.find(substringOne) == -1 and newEvent.name.find(substringTwo) == -1 and newEvent.name.find(substringThree) == -1 and newEvent.name.find(substringFour) == -1:
                eventList.append(newEvent)
    return eventList

#writes event data to a JSON file to be sent to Firebase & ultimately read by application
def writeToJSON(eventList):
    data = {}
    data["eventList"] = []
    for event in eventList:
        newEvent = {}
        newEvent["guid"] = event.guid
        newEvent["name"] = event.name
        newEvent["time"] = event.time
        newEvent["endTime"] = event.endTime
        newEvent["endDate"] = event.endDate
        newEvent["date"] = event.date
        newEvent["daysIntoYear"] = event.daysIntoYear
        newEvent["url"] = event.url
        newEvent["summary"] = event.summary
        newEvent["description"] = event.description
        newEvent["contactName"] = event.contactName
        newEvent["contactPhone"] = event.contactPhone
        newEvent["contactMail"] = event.contactMail
        newEvent["mainLocation"] = event.mainLocation
        if event.mainEventType != None: #conflicts sometimes occur when event type & location are the same, causing mainEventType to be None/null/nil.  this ensures there is a main event type
            newEvent["mainEventType"] = event.mainEventType
        else:
            i = 0
            found = False
            while found == False:
                while event.eventTypes[i].eventTypeName == None:
                    i += 1
                newEvent["mainEventType"] = event.eventTypes[i].eventTypeName
                found = True
        newEvent["address"] = event.mainAddress
        newEvent["city"] = event.mainCity
        newEvent["state"] = event.mainState
        newEvent["zip"] = event.mainZip
        newEvent["lat"] = event.mainLat
        newEvent["lon"] = event.mainLon
        newEvent["hasCultural"] = event.hasCultural
        newEvent["subLocations"] = []
        for location in event.subLocations:
            newEvent["subLocations"].append(location.name)
        newEvent["eventTypes"] = []
        for ev in event.eventTypes:
            if (ev.eventTypeName != "") & (ev.eventTypeName != None): #hacky workaround but sometimes "" or None gets put in this array.  didn't feel like finding the bug, written JSON is correct
                newEvent["eventTypes"].append((ev.eventTypeName))
        data["eventList"].append(newEvent)
        with open('EventInformation.json', 'w', encoding='utf-8') as outfile:
            json.dump(data, outfile, ensure_ascii=False, indent=4)
    return data

def writeAssociationJSON(whatTypeDic): #used for search functionality in the app.  extra logic is to remove leading hyphens from sublocations
    dicWithoutDashes = {}
    subDic = {}
    for key, value in whatTypeDic.items():
        for k, v in value.items():
            if k[0] == "-":
                k = k[1:]
            subDic[k] = v
        dicWithoutDashes[key] = subDic
        subDic = {}
    with open('Associations.json', 'w', encoding='utf8') as outfile:
        json.dump(dicWithoutDashes, outfile, ensure_ascii=False, indent=4)
    return dicWithoutDashes

eventInformationJSONPath = "./EventInformation.json"
associationsJSONPath = "./Associations.json"

#Initiate parsing
whatTypeDic = parseHTML()
print("parsed HTML")
eventList = parseXML(whatTypeDic)
print("parsed XML")
eventList = writeToJSON(eventList)
print("wrote eventlist JSON")
associationData = writeAssociationJSON(whatTypeDic)
associationListData = {}
associationListData["associations"] = associationData
print("wrote association JSON")

ref = db.reference('Events/eventList')
refEventAssociations = db.reference('EventTypeAssociations')
refLocAssociations = db.reference('LocationAssociations')
try:
    ref.delete()
except:
    print("Couldn't delete from DB or couldn't find in DB...")
try:
    refEventAssociations.delete()
except:
    print("Couldn't delete event type associations from DB or couldn't find in DB...")
try:
    refLocAssociations.delete()
except:
    print("Couldn't delete location associations from DB or couldn't find in DB...")
ref = db.reference('/Events')
ref.set(eventList)
refEventAssociations = db.reference('/EventTypeAssociations')
refEventAssociations.set(eventAssocationDic)#(associationListData)
refLocAssociations = db.reference('/LocationAssociations')
refLocAssociations.set(locAssociationDic)



"""
#print("hi")
try:
    print("Attempting to delete old JSON data from Firebase")
    blob = bucket.blob('EventInformation.json')
    blob.delete()
    blob = bucket.blob('Associations.json')
    blob.delete()
    #bucket.delete("EventInformation.json")
    #storage = firebase.storage()
    #storage.delete("EventInformation.json")
except:
    "Couldn't delete from Firebase"

try:
    print("Updating JSON data in Firebase")
    blob = bucket.blob('EventInformation.json')
    outfile = './EventInformation.json'
    blob.upload_from_filename(outfile)
    blob = bucket.blob('Associations.json')
    outfile = './Associations.json'
    blob.upload_from_filename(outfile)
except:
    "Couldn't write to Firebase"
"""