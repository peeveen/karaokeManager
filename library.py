from collections import defaultdict
from colorama import Fore, Style
from textdistance import levenshtein
from os import path, walk
import threading
import random
from time import sleep
from display_functions import pad_or_ellipsize
from karaoke_file import KaraokeFile
from music_file import MusicFile
from exemptions import Exemptions
from error import Error

class Library:
	# Current background music playlist (strings from the BackgroundMusicPlaylist file)
	background_music_playlist = set([])
	# List of karaoke files (KaraokeFile objects)
	karaoke_files = []
	# List of music files (MusicFile objects)
	music_files = []
	# Dictionary of karaoke files. Key is artist, value is another dictionary of karaoke files
	# where the key is the song title, and the value is a list of tracks from one or more vendors.
	karaoke_dictionary = defaultdict()
	# Dictionary of music files. Key is artist, value is another dictionary of music files
	# where the key is the song title, and the value is a list of tracks with that title.
	music_dictionary = defaultdict()
	# Files that were ignored
	ignored_files=[]
	karaoke_filename_errors=[]
	music_filename_errors=[]
	bgm_manifest=[]
	# Thread that will periodically choose a random karaoke file and write it to the suggestion file.
	suggestor_thread = None
	# Flag to stop the suggestion thread.
	stop_suggestions = False
	# All our lovely exemption info
	exemptions=None

	def __init__(self,config,errors):
		self.exemptions = Exemptions(config, errors)
		self.build_song_lists([],config,errors)

	# Reads the background music playlist into memory
	def get_background_music_playlist(self, config):
		playlist = set([])
		backgroundMusicFilePath=config.paths.bgm_playlist
		if path.isfile(backgroundMusicFilePath):
			with open(backgroundMusicFilePath, mode="r", encoding="utf-8") as f:
				lines = f.readlines()
				for line in lines:
					line = line.strip()
					if(len(line) > 0):
						playlist.add(line.lower())
		return playlist

	# Builds the dictionaries of karaoke and music tracks
	def build_dictionaries(self):
		self.karaoke_dictionary = defaultdict()
		for songFile in self.karaoke_files:
			self.karaoke_dictionary.setdefault(songFile.artist, defaultdict()).setdefault(
				songFile.title, []).append(songFile)
		self.music_dictionary = defaultdict()
		for songFile in self.music_files:
			self.music_dictionary.setdefault(songFile.artist, defaultdict()).setdefault(
				songFile.title, []).append(songFile)

	# Scans the files in one or more folders.
	def scan_files(self,filePaths,filePatterns,scanFileFunction,secondaryFileCollection):
		scannedFiles=[]
		filenameErrors=[]
		ignoredFiles=[]
		for filePath in filePaths:
			for root, _, files in walk(filePath):
				print(pad_or_ellipsize(f"Scanning {root}", 119), end="\r")
				for file in files:
					scanFileFunction(root,file,filePatterns,scannedFiles,secondaryFileCollection,filenameErrors,ignoredFiles)
		return scannedFiles,filenameErrors,ignoredFiles

	# Builds the karaoke and music lists by analysing folder contents.
	def build_song_lists(self, params, config, errors):
		self.bgm_playlist=self.get_background_music_playlist(config)
		self.backgroundMusic=[]
		self.karaokeFilenameErrors=[]
		self.musicFilenameErrors=[]
		self.ignoredFiles=[]
		self.karaoke_files=[]
		self.music_files=[]
		quickanalyze = any(params) and (params[0] == "quickanalyze" or params[0] == "q")
		fullanalyze = any(params) and (params[0] == "analyze" or params[0] == "a")
		self.karaoke_files, karaokeFilenameErrors, ignoredKaraokeFiles=self.scan_files(config.paths.karaoke,config.karaoke_patterns,self.scan_karaoke_file,None)
		self.music_files, musicFilenameErrors, ignoredMusicFiles=self.scan_files(config.paths.music,config.music_patterns,self.scan_music_file,self.bgm_manifest)
		filenameErrors = karaokeFilenameErrors+musicFilenameErrors
		ignoredFiles = ignoredKaraokeFiles+ignoredMusicFiles
		write_text_file(filenameErrors,config.paths.filename_errors,errors)
		write_text_file(ignoredFiles,config.paths.ignored_files,errors)
		# Whatever's left in the background music playlist will be missing files.
		write_text_file(self.bgm_playlist,config.paths.missing_playlist_entries,errors)
		write_text_file(self.bgm_manifest,config.paths.bgm_manifest,errors)
		self.build_dictionaries()
		self.start_suggestion_thread(config)
		anythingToReport = any(filenameErrors) or any(self.bgm_playlist)
		duplicates=[]
		songErrors=[]
		if quickanalyze or fullanalyze:
			self.analyze_files(config,fullanalyze,songErrors,duplicates,errors)
			anythingToReport = anythingToReport or any(songErrors) or any(duplicates)
		if anythingToReport:
			scanCompleteMessage=pad_or_ellipsize("Scan complete.", 119)
			print(f"{Fore.WHITE}{Style.BRIGHT}{scanCompleteMessage}")
			print(f"{Fore.RED}{Style.BRIGHT}Bad filenames:{Style.RESET_ALL} {len(filenameErrors)}")
			print(f"{Fore.GREEN}{Style.BRIGHT}Ignored files:{Style.RESET_ALL} {len(ignoredFiles)}")
			print(f"{Fore.YELLOW}{Style.BRIGHT}Artist/title problems:{Style.RESET_ALL} {len(songErrors)}")
			print(f"{Fore.CYAN}{Style.BRIGHT}Duplicate files:{Style.RESET_ALL} {len(duplicates)}")
			print(f"{Fore.MAGENTA}{Style.BRIGHT}Missing playlist entries:{Style.RESET_ALL} {len(self.bgm_playlist)}")
			try:
				input("Press Enter to continue ...")
			except EOFError:
				pass
		# Helper function for dictionary sorting.
		def getMusicFileKey(file):
			return file.artist
		self.music_files.sort(key=getMusicFileKey)
		self.karaoke_files.sort(key=getMusicFileKey)

	# Function to stop the suggestion thread.
	def stop_suggestion_thread(self):
		if not self.suggestor_thread is None:
			self.stop_suggestions = True
			self.suggestor_thread.join()
		self.stop_suggestions = False

	# Function to start the suggestion thread.
	def start_suggestion_thread(self, config):
		self.stop_suggestion_thread()
		suggestor_thread = threading.Thread(
			target=self.random_song_suggestion_generator_thread, args=[config.paths.random_suggestion,])
		suggestor_thread.daemon = True
		suggestor_thread.start()

	# Thread that periodically writes a random karaoke suggestion to a file.
	def random_song_suggestion_generator_thread(self,path):
		random.seed()
		counter = 0
		while not self.stop_suggestions:
			if counter == 0:
				counter = 20
				if any(self.karaoke_dictionary):
					artistKeys = list(self.karaoke_dictionary.keys())
					randomArtistIndex = random.randrange(len(self.karaoke_dictionary))
					artistString = artistKeys[randomArtistIndex]
					artistDict = self.karaoke_dictionary[artistString]
					randomSongIndex = random.randrange(len(artistDict))
					songKeys = list(artistDict.keys())
					songString = songKeys[randomSongIndex]
					suggestionString = f"{artistString}\n{songString}\n"
					try:
						with open(path, mode="w", encoding="utf-8") as f:
							f.writelines(suggestionString)
					except PermissionError:
						pass
			else:
				counter -= 1
			sleep(0.5)

	# Scans a list of files for potential duplicates, bad filenames, etc.
	def analyze_file_set(self,config,files,dictionary,fullanalysis,songErrors,duplicates,errors):
		# Checks two strings for similarity.
		def similarity(s1, s2):
			longerLength = max(len(s1),len(s2))
			if longerLength == 0:
				return 1.0
			return (longerLength - levenshtein(s1, s2)) / longerLength

		self.get_exemptions(config, errors)
		artists = set([])
		artistList = []
		artistLowerList = []

		lastPercent = -1
		counter = 0
		songProgressCount = len(dictionary)
		for artist, songDict in dictionary.items():
			counter += 1
			percent = round((counter/songProgressCount)*100.0)
			if percent > lastPercent:
				print(pad_or_ellipsize(f"Looking for duplicates: {percent}% done", 119), end="\r")
				lastPercent = percent
			for songCollection in songDict.values():
				if len(songCollection)>1:
					duplicates.extend(songCollection[1:])
		for song in files:
			if not song.artist in artists:
				artists.add(song.artist)
				artistList.append(song.artist)
				artistLowerList.append(song.lower_artist)
		for artist in artists:
			firstletter = artist[0]
			if firstletter.isalpha() and firstletter.islower():
				if not self.exemptions.is_exempt_from_lower_case_check(artist):
					error = f"Artist \"{artist}\" is not capitalised."
					songErrors.append(error)
			if artist.startswith("The "):
				if artist[4:] in artists and not self.exemptions.is_exempt_from_the_check(artist):
					error = f"Artist \"{artist}\" has a non-The variant."
					songErrors.append(error)
		artistCount = len(artistList)
		songCount = len(files)
		songProgressCount = round((songCount*songCount)/2)
		artistProgressCount = round((artistCount*artistCount)/2)
		counter = 0
		lastPercent = -1
		for i in range(0, artistCount):
			artist = artistList[i]
			artistLower = artistLowerList[i]
			ampersandFirstIndex = artist.find(" & ")
			ampersandLastIndex = artist.rfind(" & ")
			if ampersandFirstIndex != -1 and ampersandLastIndex == ampersandFirstIndex:
				bit1 = artist[0:ampersandFirstIndex]
				bit2 = artist[ampersandFirstIndex+3:]
				if bit2 != bit1:
					if not self.exemptions.is_exempt_from_reversal_check(bit1, bit2):
						reverseCheck = bit2+" & "+bit1
						if reverseCheck in artists:
							error = f"Artist \"{artist}\" also appears as \"{reverseCheck}\"."
							songErrors.append(error)
			for j in range(i+1, artistCount):
				counter += 1
				percent = round((counter/artistProgressCount)*100.0)
				if percent > lastPercent:
					print(pad_or_ellipsize(f"Analyzing artists: {percent}% done", 119), end="\r")
					lastPercent = percent
				compareArtist = artistList[j]
				compareArtistLower = artistLowerList[j]
				if artistLower == compareArtistLower and artist != compareArtist:
					error = f"Artist \"{artist}\" has a case variation: \"{compareArtist}\"."
					songErrors.append(error)
		songProgressCount = round((songCount*songCount)/2)
		counter = 0
		lastPercent = -1
		for i in range(0, songCount):
			songFile = files[i]
			songTitle = songFile.title
			songTitleLower = songFile.lower_title
			firstletter = songTitle[0]
			if firstletter.isalpha() and firstletter.islower():
				if not self.exemptions.is_exempt_from_lower_case_check(songTitle):
					error = f"Title \"{songTitle}\" is not capitalised."
					songErrors.append(error)
			for j in range(i+1, songCount):
				counter += 1
				percent = round((counter/songProgressCount)*100.0)
				if percent > lastPercent:
					print(pad_or_ellipsize(f"Analyzing song titles (simple analysis): {percent}% done", 119), end="\r")
					lastPercent = percent
				compareTitle = files[j].title
				compareTitleLower = files[j].lower_title
				if songTitle != compareTitle:
					if songTitleLower == compareTitleLower:
						error = f"Title \"{songTitle}\" has a case variation: \"{compareTitle}\"."
						songErrors.append(error)
		lastPercent = -1
		counter = 0
		songProgressCount = len(dictionary)
		if fullanalysis:
			for artist, songDict in dictionary.items():
				counter += 1
				percent = round((counter/songProgressCount)*100.0)
				if percent > lastPercent:
					print(pad_or_ellipsize(f"Analyzing song titles (complex analysis): {percent}% done"), end="\r")
					lastPercent = percent
				keys = list(songDict.keys())
				for i in range(0, len(keys)):
					for j in range(i+1, len(keys)):
						if not self.exemptions.is_exempt_from_similarity_check(keys[i], keys[j]):
							similarityCalc = similarity(keys[i], keys[j])
							if similarityCalc < 1.0 and similarityCalc > 0.9:
								error = f"Title \"{keys[i]}\" looks very similar to \"{keys[j]}\"."
								songErrors.append(error)

	# Analyse set of files for duplicates, filename errors, etc, and report results.
	def analyze_files_per_category(self,config,full,songErrors,duplicates,files,dictionary,dupPath,errPath,descr,errors):
		dups=[]
		errs=[]
		print(pad_or_ellipsize(f"Analyzing {descr} files...", 119))
		self.analyze_file_set(config,files,dictionary,full,errs,dups,errors)
		duplicates.extend(dups)
		songErrors.extend(errs)
		try:
			with open(dupPath, mode="w", encoding="utf-8") as f:
				for duplicate in dups:
					f.writelines(duplicate.artist+" - "+duplicate.title+"\n")
		except PermissionError:
			errors.append(Error("Failed to write duplicates file."))
		try:
			with open(errPath, mode="w", encoding="utf-8") as f:
				for songError in errs:
					f.writelines(f"{songError}\n")
		except PermissionError:
			errors.append(Error("Failed to write artist or title errors file."))

	# Analyses both the karaoke and music file sets for errors.
	def analyze_files(self,config,full,songErrors,duplicates,errors):
		self.analyze_files_per_category(config,full,songErrors,duplicates,self.music_files,self.music_dictionary,config.paths.music_duplicates,config.paths.music_errors,"music",errors)
		self.analyze_files_per_category(config,full,songErrors,duplicates,self.karaoke_files,self.karaoke_dictionary,config.paths.karaoke_duplicates,config.paths.karaoke_errors,"karaoke",errors)

	def create_karaoke_file(self,path, groupMap):
		vendor=groupMap["vendor"]
		if vendor is None:
			vendor="UNKNOWN"
		return KaraokeFile(path,groupMap["artist"],groupMap["title"],vendor)

	def create_music_file(self,path, groupMap):
		return MusicFile(path,groupMap["artist"],groupMap["title"])

	def parse_filename(self,filePath, filename, patterns, errors, ignored, fileBuilder):
		nameWithoutExtension, extension = path.splitext(filename)
		extension=extension.strip('.')
		validPatterns=list(filter(lambda pattern: pattern.extension_matches(extension), patterns))
		if any(validPatterns):
			for pattern in validPatterns:
				groupMap = pattern.parse_filename(nameWithoutExtension)
				if any(groupMap):
					file=fileBuilder(filePath, groupMap)
					if not file is None:
						return file
			errors.append(filename)
		else:
			ignored.append(filename)
		return None

	# Tries to parse a karaoke file, adding it to a collection if successful.
	def scan_karaoke_file(self,root, file,filePatterns,fileCollection, secondaryFileCollection, filenameErrors, ignoredFiles):
		karaokeFile = self.parse_filename(path.join(root,file), file, filePatterns, filenameErrors, ignoredFiles, self.create_karaoke_file)
		if not karaokeFile is None:
			fileCollection.append(karaokeFile)

	# Tries to parse a music file, adding it to a collection if successful.
	def scan_music_file(self,root, file,filePatterns,fileCollection, secondaryFileCollection, filenameErrors, ignoredFiles):
		full_path = path.join(root,file)
		musicFile = self.parse_filename(full_path, file, filePatterns, filenameErrors, ignoredFiles, self.create_music_file)
		if not musicFile is None:
			fileWithoutExtension = file[0:-4]
			if fileWithoutExtension in self.bgm_playlist:
				secondaryFileCollection.append(full_path)
				self.bgm_playlist.remove(fileWithoutExtension)
			fileCollection.append(musicFile)

# Writes a list of strings to a text file.
def write_text_file(itemList,path,errors):
	try:
		with open(path, mode="w", encoding="utf-8") as f:
			for item in itemList:
				f.writelines(f"{item}\n")
	except PermissionError:
		errors.append(Error(f"Failed to write to '{path}'."))