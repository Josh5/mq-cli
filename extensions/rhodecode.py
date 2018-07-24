#!/usr/bin/python3
#


import requests
import os
import sys
import time
import subprocess
import argparse
from lxml import html
from pprint import pprint

import xml.sax.saxutils as saxutils

try:
    import ConfigParser as configparser
except:
    import configparser as configparser



PATCH_HEADER = ""
PATCH_HEADER += "# HG changeset patch\n"
PATCH_HEADER += "# User {}\n"
PATCH_HEADER += "{}\n\n"



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

    def make_request(self, url, method, payload=None, headers=None, allow_redirects=True, files=None):
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


class Rhodecode(object):

    def __init__(self, *args, **kwargs):
        self.config = Config();
        self.config.read_config();
        if 'debug' in kwargs:
            self.debug = kwargs.get("debug");
        self.BASE_URL = self.getConfig("rhodecode_url");
        self.req = REMOTE(debug=self.debug);
        self.headers = [];

    def getConfig(self, config_id):
        if str(config_id) in self.config.getAll():
            return getattr(self.config, config_id);
        return "";

    def log(self, string):
        if self.debug:
            try:
                print('[RHODECODE]: %s' % string);
            except UnicodeEncodeError:
                # we can't anticipate everything in unicode they might throw at
                # us, but we can handle a simple BOM
                bom = unicode(codecs.BOM_UTF8, 'utf8');
                print('[RHODECODE]: %s' % string.replace(bom, ''));
            except Exception:
                pass;

    def fetch_diffs(self, _url):
        ret = self.req.make_request(_url, 'get', allow_redirects=True);
        if ret.status_code == 200:
            return ret.text;
        return False;

    def download_file(self, file_contents, filename):
        _file = os.path.join('/', 'tmp', filename);
        with open(_file, 'w') as f:
            f.write(file_contents);
        return _file;

    def get_pull_request_data(self, pull_request_id):
        pr_data = {};
        _url = self.BASE_URL + "/_admin/pull-request/" + str(pull_request_id);
        ret = self.req.make_request(_url, 'get', allow_redirects=True);
        if ret.status_code != 200:
            self.log('ERROR: unable to fine pull request. Unable to continue');
            return False;
        tree = html.fromstring(ret.text);

        # Get pull request title
        pr_title = tree.xpath('//span[@id="pr-title"]/text()');
        pr_data['title'] = "";
        if pr_title:
            pr_data['title'] = ' - "{}"'.format(pr_title[0].strip());
        else:
            self.log('ERROR: Failed to fetch pull request title');

        # Get src repo url
        repo_link = tree.xpath('//div[@class="pr-origininfo"]//span[@class="clone-url"]/a/@href');
        if repo_link:
            pr_data['repo_url'] = repo_link[0];
        else:
            self.log('ERROR: Failed to fetch original repo link. Unable to continue');
            return False;

        # Get urls for the individual diff files
        diff_links = tree.xpath('//a[@title="Raw diff"]/@href');
        pr_data['raw_diffs'] = [];
        for link in diff_links:
            try:
                new_link = "{}{}/diff/{}".format(self.BASE_URL,pr_data['repo_url'],link.split("/diff/")[1]);
                pr_data['raw_diffs'].append(new_link);
            except:
                self.log('ERROR: Failed to generate diff urls. Unable to continue');
                return False;

        # Get user
        commit_users = tree.xpath('//div[@class="rc-user tooltip"]/@title');
        if not commit_users:
            self.log('ERROR: Failed to fetch pull request user. Unable to continue');
            return False;
        pr_data['user'] = saxutils.unescape(commit_users[0]);

        # Get commit message
        commit_description_block = tree.xpath('//div[@id="pr-desc"]');
        if not commit_description_block:
            self.log('ERROR: Failed to fetch pull request description. Unable to continue');
            return False;
        pr_data['description'] = commit_description_block[0].text_content().strip().replace("- ","",1);

        return pr_data;

    def get_diffs_and_combine(self, pr_data):
        combined_diff_string = PATCH_HEADER.format(pr_data['user'],pr_data['description']);
        for link in pr_data['raw_diffs']:
            res = self.fetch_diffs(link);
            if res:
                combined_diff_string += res
        return combined_diff_string;

    def generate_patch_from_pull_request(self, pull_request_id):
        print("");
        print("Importing patch from RhodeCode pull request...");
        print("");
        pr_data = self.get_pull_request_data(pull_request_id);
        if pr_data:
            print('Fetching pull request #{} {}'.format(str(pull_request_id),pr_data['title']));
            file_contents = self.get_diffs_and_combine(pr_data);
            res_file = self.download_file(file_contents, "PULLREQUEST_{}.patch".format(pull_request_id));
            if res_file:
                print("");
                print("");
                cmd = ['mq', 'import', res_file];
                try:
                    p = subprocess.check_call(cmd);
                    if p == 0:
                        return True;
                except:
                    pass;
        print("");
        print("No patch imported.");
        return False;



def get_params():
    parser = argparse.ArgumentParser();
    parser.add_argument('--debug', dest='debugging',
                        action='store_true', help='Enable debugging', default=False);
    parser.add_argument('command', nargs='?', default='help',
                        help='What command should be run.');
    parser.add_argument('argument', nargs='?', default='help',
                        help='Pull Request ID in RhodeCode');
    args = parser.parse_args();
    return args;


if __name__ == '__main__':
    args = get_params()
    rhodecode = Rhodecode(debug=args.debugging)
    if args.command == "help":
        print("        rhodecode        Fetch pull requests from RhodeCode and import it as a patch.");
        print("                         Usage:");
        print("                                 mq rhodecode primport [PULLREQUEST NUMBER]");
    if args.command == "primport":
        rhodecode.generate_patch_from_pull_request(args.argument);
