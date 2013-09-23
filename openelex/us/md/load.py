from os.path import exists, join
from openelex.base.load import BaseLoader
from openelex.us.md import fetch
from mongoengine import *
from openelex.models import Candidate, Result, Contest
import json
import unicodecsv

"""
Usage:

from openelex.us.md import load
l = load.LoadResults()
l.run('2012-11-06')

Maybe add flags to load only certain reporting levels? Should we have year-based loaders?

re-run filenames loader to write election_dates
pass files as hash with keys of election_dates and lists of interior files, with jurisdiction names
"""

class LoadResults(BaseLoader):
    
    def run(self, date):
        # date can be year or YYYY-MM-DD date
        files = self.filenames[str(date[0:4])] # grab all files for that year
        self.check_cache(str(date[0:4]), files)
        if len(date) > 4:
            files = [f for f in files if date.replace('-', '') in f['generated_name']]
        for file in files:
            self.process_file(file)
        
    def check_cache(self, year, files):
        uncached_files = []
        for f in files:
            if not exists(join(self.cache_dir, f['generated_name'])):
                uncached_files.append(f)
        if len(uncached_files) > 0:
            fetch_files(year, uncached_files)
        
    def fetch_files(self, year, files):
        f = fetch.FetchResults()
        f.run(year, files)
        # logging?
    
    def process_file(self, file):
        connect('openelex_md_tester')
        print file['generated_name']
        with open(join(self.cache_dir, file['generated_name']), 'rU') as csvfile:
            reader = unicodecsv.DictReader(csvfile, encoding='latin-1')
            if 'state_legislative' in file['generated_name']:
                reporting_level = 'state_legislative'
                districts = [j for j in reader.fieldnames if j not in ['Vote Type (FOR=1,AGAINST=2)', 'County', 'Candidate Name', 'Party', 'Office Name', 'Office District', 'Winner', 'Write-In?']]
            elif 'precinct' in file['generated_name']:
                reporting_level = 'precinct'
                jurisdiction = file['name']
            else:
                reporting_level = 'county'
                jurisdiction = file['name']
            for row in reader:
                if not row['Office Name'].strip() in ['President - Vice Pres', 'U.S. Senator', 'U.S. Congress', 'Governor / Lt. Governor', 'Comptroller', 'Attorney General', 'State Senator', 'House of Delegates']:
                    continue
                # parse candidate - we get full names
                name = self.parse_name(row['Candidate Name'])
                # if office is president, then skip state in lookup, otherwise use
                if row['Office Name'] == 'President - Vice Pres':
                    candidate = Candidate(state='US', given_name=name.first, additional_name=name.middle, family_name=name.last, suffix=name.suffix, name=name.full_name)
                else:
                    candidate = Candidate(state=self.state.upper(), given_name=name.first, additional_name=name.middle, family_name=name.last, suffix=name.suffix, name=name.full_name)
                # sometimes write-in field not present
                try:
                    if row['Write-In?'] == 'Y':
                        write_in = True
                    else:
                        write_in = False
                except KeyError:
                    write_in = None
                if row['Winner'] == 'Y':
                    winner = True
                else:
                    winner = False
                if reporting_level == 'state_legislative':
                    self.process_state_legislative(row, districts, candidate, reporting_level, write_in, winner)
                elif reporting_level == 'county':
                    self.process_county(row, file['ocd_id'], jurisdiction, candidate, reporting_level, write_in, winner)
                elif reporting_level == 'precinct':
                    self.process_precinct(row, file['ocd_id'], jurisdiction, candidate, reporting_level, write_in, winner)
    
    def process_state_legislative(self, row, districts, candidate, reporting_level, write_in, winner):
        for district in districts:
            if row[district].strip() == '':
                total_votes = 0
            else:
                total_votes = row[district]
            if row['Party'] not in candidate.raw_parties:
                candidate.raw_parties.append(row['Party'])
            ocd = "ocd-division/country:us/state:md/sldl:%s" % district.strip().split(' ')[1]
            result = Result(ocd_id=ocd, jurisdiction=district.strip(), raw_office=row['Office Name'].strip()+' '+row['Office District'], reporting_level=reporting_level, candidate=candidate, party=row['Party'], write_in=write_in, total_votes=total_votes, winner=winner).save()
    
    def process_county(self, ocd_id, jurisdiction, row, candidate, reporting_level, write_in, winner):
        try:
            total_votes = row['Total Votes']
        except:
            print row
        #vote_breakdowns = { 'election_night_total': row['Election Night Votes'], 'absentee_total': row['Absentees Votes'], 'provisional_total': row['Provisional Votes'], 'second_absentee_total': row['2nd Absentees Votes']}
        result = Result(ocd_id=ocd_id, jurisdiction=jurisdiction, raw_office=row['Office Name']+' '+row['Office District'], reporting_level=reporting_level, candidate=candidate, party=row['Party'], write_in=write_in, total_votes=total_votes, vote_breakdowns={}).save()
        
    def process_precinct(self, ocd_id, row, jurisdiction, candidate, reporting_level, write_in, winner):
        jurisdiction = jurisdiction+' '+str(row['Election District'])+"-"+str(row['Election Precinct'])
        total_votes = row['Election Night Votes']
        vote_breakdowns = { 'election_night_total': row['Election Night Votes']}
        result = Result(ocd_id=ocd_id, jurisdiction=jurisdiction, raw_office=row['Office Name']+' '+row['Office District'], reporting_level=reporting_level, candidate=candidate, party=row['Party'], write_in=write_in, total_votes=total_votes, vote_breakdowns=vote_breakdowns).save()
        
                