#!/usr/bin/osascript

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Open File with emacsclient
# @raycast.mode silent

# Optional parameters:
# @raycast.icon 🤖

# Documentation:
# @raycast.author Martin Liu

-- https://gist.github.com/tru2dagame/600e29e082eaae280d91f746ed4918b0
-- get the file path from the finder
tell application "Finder" to set theItems to selection
set thePaths to ""
repeat with i in theItems
	set thisItem to POSIX path of (i as alias)
	set thePaths to thePaths & thisItem & return
end repeat
set filePath to thePaths

-- remove \n of the file path
set AppleScript's text item delimiters to {return & linefeed, return, linefeed, character id 8233, character id 8232}
set newText to text items of filePath
set AppleScript's text item delimiters to {" "}
set theText to newText as text

-- remove the last whitespace
set theText to trim(theText)

-- add escape: convert ' and & to \' and \&
set theText to searchAndReplace(theText, "'", "\\'")
set theText to searchAndReplace(theText, "&", "\\&")
-- add escape to whitespace
set theText to searchAndReplace(theText, " ", "\\ ")

-- use shell script to let the emacsclient work
do shell script "emacsclient -a emacs " & theText & " "

on trim(theString)
	return (do shell script "echo \"" & theString & "\" | xargs")
end trim

on searchAndReplace(targetText, searchText, replaceText)
	set newText to ""
	set {tid, my text item delimiters} to {my text item delimiters, searchText}
	try
		set textList to every text item of targetText
		set my text item delimiters to replaceText
		set newText to textList as text
		set my text item delimiters to tid
	on error
		set my text item delimiters to tid
		set newText to targetText
	end try
	return newText
end searchAndReplace
