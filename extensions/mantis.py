#!/usr/bin/python3
#


import requests
import os
import sys
import time
import hashlib
import getpass
import json
import subprocess
import argparse
from lxml import html
from pprint import pprint

try:
    import ConfigParser as configparser
except:
    import configparser as configparser



class Config():
    def __init__(self):
        self.config = configparser.RawConfigParser()

    def read_config(self):
        self.config.read(os.path.join(os.path.expanduser("~"), ".hgrc"))
        for each_section in self.config.sections():
            if each_section == 'mq':
                for (each_key, each_val) in self.config.items(each_section):
                    setattr(self, each_key, each_val)

    def getAll(self):
        return [attr for attr in dir(self) if (not attr.startswith('__') and not attr.startswith('getAll'))]


class REMOTE():
    def __init__(self, timeout=20, debug=False):
        self.timeout = timeout
        self.debug = debug
        # Configure session and cookies
        self.http_session = requests.Session()

    def log(self, string):
        if self.debug:
            try:
                print('[REMOTE]: %s' % string)
            except UnicodeEncodeError:
                # we can't anticipate everything in unicode they might throw at
                # us, but we can handle a simple BOM
                bom = unicode(codecs.BOM_UTF8, 'utf8')
                print('[REMOTE]: %s' % string.replace(bom, ''))
            except Exception:
                pass

    def make_request(self, url, method, payload=None, headers=None, allow_redirects=False, files=None):
        """Make an http request. Return the response."""
        self.log('Request URL: %s' % url)
        self.log('Headers: %s' % headers)
        self.log('Payload: %s' % payload)
        try:
            if method == 'get':
                req = self.http_session.get(
                    url, params=payload, headers=headers, allow_redirects=allow_redirects, timeout=self.timeout)
            elif method == 'files':
                req = self.http_session.post(
                    url, data=payload, files=files, headers=headers, allow_redirects=allow_redirects, timeout=self.timeout)
            elif method == 'getfile':
                req = self.http_session.get(
                    url, params=payload, headers=headers, allow_redirects=allow_redirects, timeout=self.timeout, stream=True)
            else:  # post
                req = self.http_session.post(
                    url, data=payload, headers=headers, allow_redirects=allow_redirects, timeout=self.timeout)
            req.raise_for_status()
            self.log('Response code: %s' % req.status_code)
            #self.log('Response: %s' % req.content)
            return req
        except requests.exceptions.HTTPError as error:
            self.log('An HTTP error occurred: %s' % error)
            raise
        except requests.exceptions.ProxyError:
            self.log('Error connecting to proxy server')
            raise
        except requests.exceptions.ConnectionError as error:
            self.log('Connection Error: - %s' % error.message)
            raise
        except requests.exceptions.RequestException as error:
            self.log('Error: - %s' % error.value)
            raise


class Mantis(object):

    def __init__(self, *args, **kwargs):
        self.config     = Config()
        self.config.read_config()
        if 'debug' in kwargs:
            self.debug  = kwargs.get("debug")
        self.USERNAME   = self.getConfig("mantis_username")
        self.PASSWORD   = self.getConfig("mantis_password")
        self.LOGIN_URL  = self.getConfig("mantis_login_url")
        self.BASE_URL   = self.getConfig("mantis_url")
        self.req        = REMOTE(debug=self.debug)
        self.headers    = [];

    def getConfig(self, config_id):
        if str(config_id) in self.config.getAll():
            return getattr(self.config, config_id)
        return ""

    def log(self, string):
        if self.debug:
            try:
                print('[MANTIS]: %s' % string)
            except UnicodeEncodeError:
                # we can't anticipate everything in unicode they might throw at
                # us, but we can handle a simple BOM
                bom = unicode(codecs.BOM_UTF8, 'utf8')
                print('[MANTIS]: %s' % string.replace(bom, ''))
            except Exception:
                pass

    def login(self, redirect_issue=""):
        _url = "https://www.nsquared.co.nz/support/tickets/login.php"
        if not self.PASSWORD:
            self.PASSWORD = getpass.getpass("Enter the Password:")
        data = {
            "username": self.USERNAME,
            "password": self.PASSWORD,
            "return ": "/mantis/view.php?id=%s" % redirect_issue,
            "secure_session": "on"
        }
        ret = self.req.make_request(
            _url, 'post', payload=data, allow_redirects=False)
        self.log(ret.content)
        if ret.status_code == 302:
            self.headers = ret.headers
            self.log("successfully logged in")
            return True
        return False

    def list_patches_on_mantis_bug(self, issue):
        _url = self.BASE_URL + "/view.php?id={}".format(issue)
        self.login()
        ret = self.req.make_request(_url, 'get')
        self.log(ret.content)
        tree = html.fromstring(ret.content)
        notes = tree.xpath('//*[contains(@class, "bugnote-note")]//a[text()]')
        issue_patches = {}
        for note in notes:
            text = note.xpath('text()')
            if isinstance(text, list):
                text = text[0]
            if 'issue' in text.lower():
                link = note.xpath('@href')[0]
                if isinstance(link, list):
                    link = link[0]
                issue_patches[text] = link
        return issue_patches

    def download_file(self, url, filename):
        _file   = os.path.join('/', 'tmp', filename)
        _url    = self.BASE_URL + "/{}".format(url)
        ret     = self.req.make_request(_url, 'getfile')
        if ret.status_code == 200:
            with open(_file, 'wb') as f:
                for chunk in ret.iter_content(chunk_size=1024): 
                    if chunk:
                        f.write(chunk)
            return _file
        return False

    def import_patch_from_mantis(self, issue=""):
        print("")
        print("Importing patch from mantis...")
        print("")
        while not issue:
            issue = input('Enter an issue number: ')
        patch_list = self.list_patches_on_mantis_bug(issue);
        count = 1
        selection_list = {}
        print("")
        for key in patch_list:
            print("      {}) {}".format(count, key))
            selection_list[str(count)] = patch_list[key]
            count += 1
        print("")
        selection = input("Select a patch from the list above: ")
        if selection and selection in selection_list:
            selected_url = selection_list[selection]
            res_file = self.download_file(selected_url, "ISSUE_{}.patch".format(issue))
            if res_file:
                print("")
                print("")
                cmd = ['mq', 'import', res_file, '--name={}'.format(issue)]
                p = subprocess.check_call(cmd)
                if p == 0:
                    return True
        else:
            print("")
            print("That was not a valid selection.")
        print("No patch imported.")
        return False

    def upload(self, file, issue):
        global req
        issue_url = self.BASE_URL + '/view.php?id={}'.format(issue)
        ret = req.make_request(issue_url, 'get', allow_redirects=True)
        self.log(ret.headers)
        self.log(ret.cookies)
        tree = html.fromstring(ret.content)
        bugnote_add_token = tree.xpath(
            '//input[@name="bugnote_add_token"]/@value')
        bug_id = tree.xpath('//input[@name="bug_id"]/@value')
        bugnote_text = tree.xpath('//input[@name="bugnote_text"]/@value')
        max_file_size = tree.xpath('//input[@name="max_file_size"]/@value')
        #bugnote_add_token = ""
        if os.path.exists(file):
            self.log("uploading file " + file)
            #files = {'ISSUE_12440_gocabinets.hg.patch': open(file, 'rb')}
            #files = {"file": ("ISSUE_12440_gocabinets.hg.patch", open(filepath, "rb"))}
            headers = {
                "Accept": "application/json",
                "Origin": "https://www.nsquared.co.nz",
                "Host": "www.nsquared.co.nz",
                "Referer": issue_url,
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.75 Safari/537.36",
                "X-Requested-With": "XMLHttpRequest",
            }
            data = {
                'bugnote_add_token': bugnote_add_token[0] if bugnote_add_token else "",
                'bug_id': bug_id[0] if bug_id else "",
                'bugnote_text': bugnote_text[0] if bugnote_text else "",
                'max_file_size': max_file_size[0] if max_file_size else "",
                'file-name': 'Filename',
            }
            files = {"file": ("ISSUE_12440_gocabinets", open(
                file, "rb"), 'applicaiton-type')}
            response = req.make_request(
                issue_url, 'files', payload=data, files=files, headers=headers, allow_redirects=False)
            self.log(response)
            self.log(response.status_code)
            self.log(response.cookies)
            pprint(response.headers)
            # response.raise_for_status()
            # pprint(response.json())
            # print response.content
            # files = {'file': open('style.css')}
            # response = requests.post(url, files=files)



def get_params():
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', dest='debugging', action='store_true', help='Enable debugging', default=False)
    parser.add_argument('command', nargs='?', default='help', help='What command should be run. Import/Export')
    parser.add_argument('issue', nargs='?', default='help', help='Mantis Issue ID')

    args = parser.parse_args()
    #print(args)
    return args


if __name__ == '__main__':
    args = get_params()
    mantis = Mantis(debug=args.debugging)
    if args.command == "help":
        print("        mantis           Import or Export a patch into this project from Mantis.");
        print("                         Usage:");
        print("                                 mq mantis import [ISSUE NUMBER]");
    if args.command == "import":
        if not args.issue:
            sys.exit(1);
        mantis.import_patch_from_mantis(args.issue)
    if args.command == "export":
        print("This feature does not yet exist")

