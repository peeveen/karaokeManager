from MusicFile import MusicFile
from DisplayFunctions import padOrEllipsize
from colorama import Fore, Style

# Class describing a karaoke file
class KaraokeFile(MusicFile):
	company = None

	def __init__(self, path, artist, title, company):
		MusicFile.__init__(self, path, artist, title)
		self.company = company

	def getOptionText(self):
		result = MusicFile.getOptionText(self)
		companyText = padOrEllipsize(self.company, 20, " ")
		return result+f"{Style.BRIGHT}{Fore.YELLOW}{companyText}{Style.RESET_ALL}"

	def getSongListText(self, keyChange):
		txt = MusicFile.getSongListText(self)
		if keyChange is None or keyChange==0:
			keyChange = ""
		else:
			sign=""
			if keyChange>0:
				sign="+"
			keyChange = f"({sign}{keyChange})"
		return f"{txt} {Fore.MAGENTA}{Style.BRIGHT}{keyChange}{Style.RESET_ALL}"

