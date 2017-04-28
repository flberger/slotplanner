"""A web app to manage a barcamp slot plan.

   Copyright (c) 2017 Florian Berger <florian.berger@posteo.de>
"""

# This file is part of slotplanner.
#
# slotplanner is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# slotplanner is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with slotplanner.  If not, see <http://www.gnu.org/licenses/>.

# Work started on 29. Mar 2017.

import logging
import cherrypy
import json
import pathlib
import os
import datetime
import simple.email
import simple.html
import codecs
import threading
#from hashlib import sha256

VERSION = "0.1.0"

LOGGER = logging.getLogger("slotplanner")
LOGGER.setLevel(logging.DEBUG)
STDERR_FORMATTER = logging.Formatter("slotplanner [{levelname}] {funcName}(): {message} (l.{lineno})", style = "{")
STDERR_HANDLER = logging.StreamHandler()
STDERR_HANDLER.setFormatter(STDERR_FORMATTER)
LOGGER.addHandler(STDERR_HANDLER)

AUTORELOAD = False

WRITE_LOCK = threading.Lock()

LEVEL_1_ELEMENTS = 3

# Make HTML textareas more compact
#
simple.html.ROWS = 8

SLOTPLAN_TABLE_CSS = """div.slotplan_table {
    border-bottom: solid 1px black ;
    }

div.slotplan_row_odd {
    background: rgb(223, 223, 223) ;
    }

div.slotplan_header, div.slotplan_index, div.slotplan_cell {
    padding: 0.3em 0px ;
    }

div.slotplan_header {
    font-weight: bold ;
    border-bottom: solid 1px black ;
    }

div.clear {
    clear: both ;
    }

/* Default width: desktop screen */
@media only screen and (min-width: 1025px)
{
    div.slotplan_table {
        border-top: solid 1px black ;
        }

    div.slotplan_header, div.slotplan_index, div.slotplan_cell {
        float: left ;
        width: 11.6em ;
        }

    span.slotplan_hint {
        display: none ;
        }
}

/* A little smaller: tablets, small laptops etc. */
@media only screen and (min-width: 481px) and (max-width: 1024px)
{
    div.slotplan_table {
        border-top: solid 1px black ;
        }

    div.slotplan_header, div.slotplan_index, div.slotplan_cell {
        float: left ;
        width: 6em ;
        }

    span.slotplan_hint {
        display: none ;
        }
}

/* Very small: mobile phones etc. */
@media only screen and (max-width: 480px)
{
    div.slotplan_header {
        display: none ;
        }

    div.slotplan_index {
        border: solid 1px black ;
        font-weight: bold ;
        }
}
"""

MENU_CSS="""ul.menu {
    list-style-type: none ;
    margin: 0px ;
    padding: 0px ;
    }

ul.menu li {
    border: solid 1px black ;
    border-radius: 5px ;
    padding: 0.3em ;
    font-size: 75% ;
    }

ul.menu li a {
    text-decoration: none ;
    }

/* Default width: desktop screen */
@media only screen and (min-width: 1025px)
{
    ul.menu li {
        display: inline ;
        margin: 0px 1em 0px 0px ;
        }
}

/* A little smaller: tablets, small laptops etc. */
@media only screen and (min-width: 481px) and (max-width: 1024px)
{
    ul.menu li {
        display: inline ;
        margin: 0px 1em 0px 0px ;
        }
}

/* Very small: mobile phones etc. */
@media only screen and (max-width: 480px)
{
    ul.menu li {
        margin: 0px 0px 1em 0px ;
        }
}
"""

def logged_in(f):
    """A decorator to check for valid login before displaying a page.
    """

    def run_with_login_check(*args, **kwargs):

        if not cherrypy.session.get("logged_in"):

            page = simple.html.Page("Access restricted", css = args[0].config["page_css"] + MENU_CSS)

            page.append(args[0].config["page_header"])

            page.append(args[0].menu())

            page.append('<p><strong>Please <a href="/login">log in</a> to access this page.</strong></p>')

            page.append(args[0].config["page_footer"])

            return str(page)

        return f(*args, **kwargs)

    return run_with_login_check

class SlotplannerWebApp:
    """Slotplanner main class, suitable as cherrypy root.

       All data is stored in SlotplannerWebApp.slotplanner_db, which is
       a nested data structure designed for easy JSON serialisation
       an deserialisation:

       slotplanner_db =
       {
       "contributions":
           {CONTRIBUTION_ID_STRING:
               {"first_name": FIRST_NAME,
                "last_name": LAST_NAME,
                "title": TITLE,
                "twitter_handle": TWITTER_HANDLE,
                "email": EMAIL,
                "abstract": ABSTRACT
               },
            ...
           },
       "slot_dimension_names":
           [
               ["FIRST_1", "FIRST_2", ...],
               ["FIRST_1_SECOND_1", "FIRST_1_SECOND_2", ...],
               ["FIRST_2_SECOND_1", "FIRST_2_SECOND_2", ...],
               ["FIRST_1_THIRD_1", "FIRST_1_THIRD_2", ...],
               ["FIRST_2_THIRD_1", "FIRST_2_THIRD_2", ...],
               ...
           ],
       "schedule":
           {INDEX_FIRST_1_AS_STRING:
               {INDEX_SECOND_1_AS_STRING:
                   {INDEX_THIRD_1_AS_STRING: CONTRIBUTION_ID_STRING},
                   ...,
                ...
               },
            ...
           }
       }

       where FIRST_1, ... could be days, SECOND_1, ... rooms and
       THIRD_1, ... times.

       The goal is to be able to construct a human-readable slotplan
       from this data structure.

       Note that slot_dimension_names may not be sorted, but indexes
       used in schedule always refer to slot_dimension_names sorted
       in ascending order.
    """

    def __init__(self):
        """Initialise SlotplannerWebApp.
        """

        self.slotplanner_db = {"contributions": {},
                               "slot_dimension_names": [],
                               "schedule": {}
                              }

        LOGGER.debug("Attempting to read serialised data")

        try:
            with pathlib.Path(os.environ["PWD"], "slotplanner_db.json").open("rt", encoding = "utf8") as f:

                self.slotplanner_db = json.loads(f.read())

        except:

            LOGGER.info("Error reading database from file, starting fresh")

            # Using already initialised self.slotplanner_db

        LOGGER.debug("Attempting to read config")

        self.config = {"__builtins__": None}

        conf_path = pathlib.Path(os.environ["PWD"], "slotplanner.conf")
            
        try:
            with conf_path.open("rt", encoding = "utf8") as f:

                # The threat model is that anyone who can access the
                # config can access this source and hence execute
                # arbitrary code anyway.
                #
                exec(f.read(), self.config)
                
        except:
            
            LOGGER.error("Config file slotplanner.conf not found. Creating a default one at {}".format(conf_path))

            with WRITE_LOCK:

                with conf_path.open("wt", encoding = "utf8") as f:

                    config_options = ['event = "Some Event"',
                                      'contact_email = "contact@domain"',
                                      'participants_emails = ["participant_1@domain"]',
                                      "page_css = ''",
                                      "page_header = '<p>Some Event</p>'",
                                      "page_footer = '<p>Powered by <a href=\"http://florian-berger.de/en/software/slotplanner\">slotplanner</a></p>'",
                                      'email_sender = "contact@domain"',
                                      'email_recipients = ["organiser@domain"]',
                                      'email_host = "smtp.domain"',
                                      'email_user = "contact@domain"',
                                      'email_password_rot13 = "********"',
                                      'admin_password = "admin"',
                                      'server_port = 8311',
                                      'server_threads = 4'
                                     ]

                    f.write("\n".join(config_options) + "\n")

            raise
            
        # Make self.__call__ visible to cherrypy
        #
        self.exposed = True

        return

    def __call__(self):
        """Display the root page with the current slotplan.
        """

        page = simple.html.Page("slotplanner - {}".format(self.config["event"]), css = self.config["page_css"] + SLOTPLAN_TABLE_CSS + MENU_CSS)

        page.append(self.config["page_header"])

        page.append(self.menu())

        page.append('<h1>Slotplan for {}</h1>'.format(self.config["event"]))

        page.append(self.render_slotplan())
            
        page.append(self.config["page_footer"])

        return str(page)

    def current_time_printable(self):
        """Return a printable representation of the current time.
        """

        current_time = datetime.datetime.now()

        return "{}-{}-{}-{}_{}_{}".format(current_time.year,
                                          current_time.month,
                                          current_time.day,
                                          current_time.hour,
                                          current_time.minute,
                                          current_time.second)

    def write_db(self):
        """Serialise the database to disk.
        """

        if pathlib.Path(os.environ["PWD"], "slotplanner_db.json").exists():

            # Silently replace any existing backup for this second
            #
            os.replace(str(pathlib.Path(os.environ["PWD"], "slotplanner_db.json")),
                       str(pathlib.Path(os.environ["PWD"],
                                        "slotplanner_db-{}.json".format(self.current_time_printable()))))

        with WRITE_LOCK:

            with pathlib.Path(os.environ["PWD"], "slotplanner_db.json").open("wt", encoding = "utf8") as f:

                # Write a human-readable, diff- and version
                # control-friendly representation
                #
                f.write(json.dumps(self.slotplanner_db,
                                   indent = 4,
                                   sort_keys = True))

        return

    def write_log(self, message):
        """Append a timestamp and message to logfile.
        """

        with WRITE_LOCK:

            with pathlib.Path(os.environ["PWD"], "slotplanner.log").open("at", encoding = "utf8") as f:

                f.write("{}    {}\n".format(self.current_time_printable(), message))

        return

    def test(self):
        """Test various things, e.g. data serialisation.
        """

        LOGGER.debug(self.slotplanner_db)

        LOGGER.debug("Overwriting slotplanner_db with sample data")

        self.slotplanner_db = {"contributions": {},
                               "slot_dimension_names": [],
                               "schedule": {}
                              }

        self.slotplanner_db["contributions"]["123"] = {"first_name": "John",
                                                    "last_name": "Doe",
                                                    "title": "My Presentation",
                                                    "twitter_handle": "@invalid",
                                                    "email": "john.doe@some.tld",
                                                    "abstract": "My presenation abstract."
                                                   }

        self.slotplanner_db["slot_dimension_names"] = [["Monday", "Tuesday"],
                                                       ["Room 1", "Room 2"],
                                                       ["Room 1", "Room 2"],
                                                       ["Morning", "Afternoon"],
                                                       ["Morning", "Afternoon"],
                                                      ]
        
        self.slotplanner_db["schedule"]["0"] = {"0": {"1": "123"}}

        self.write_db()

        return

    def render_slotplan(self, swap = False):
        """Return the current slotplan as an HTML string.

           If 'swap' is True, render a form to swap contributions.
        """

        return_str = ""

        if not (len(self.slotplanner_db["schedule"])
                and len(self.slotplanner_db["contributions"])
                and len(self.slotplanner_db["slot_dimension_names"])):

            return_str += '<p><strong>Currently there is no slotplan to display.</strong></p>'

            if cherrypy.session.get("logged_in"):

                return_str += '<p>You can <a href="/schedule">schedule some contributions</a> to fill the slotplan.</p>'

            return return_str

        if swap:

            return_str += '<form action="/swap" method="POST">'
                
        for level_1_index in range(len(self.slotplanner_db["slot_dimension_names"][0])):

            return_str += '<h2>{}</h2>'.format(self.slotplanner_db["slot_dimension_names"][0][level_1_index])

            return_str += '<div class="slotplan_table">'

            return_str += '<div class="slotplan_row_even">'

            return_str += '<div class="slotplan_header">&nbsp;</div>'
                
            for level_2 in self.slotplanner_db["slot_dimension_names"][1 + level_1_index]:

                return_str += '<div class="slotplan_header">{}</div>'.format(level_2)
            
            # Close row
            #
            return_str += '<div class="clear"></div></div>'

            level_3_list = self.slotplanner_db["slot_dimension_names"][1 + len(self.slotplanner_db["slot_dimension_names"][0]) + level_1_index]

            for level_3_index in range(len(level_3_list)):

                return_str += '<div class="slotplan_row_{}">'.format({0: "even", 1: "odd"}[level_3_index % 2])
                
                return_str += '<div class="slotplan_index">{}</div>'.format(level_3_list[level_3_index])

                for level_2_index in range(len(self.slotplanner_db["slot_dimension_names"][1 + level_1_index])):

                    contribution_listing = ""

                    try:

                        contribution_id = self.slotplanner_db["schedule"][str(level_1_index)][str(level_2_index)][str(level_3_index)]

                        contribution = self.slotplanner_db["contributions"][contribution_id]

                        listing_template = '{1} {2}: <em>{3}</em>'

                        if swap:
                            listing_template = '<input type="checkbox" name="swap" value="{0}"> ' + listing_template

                        contribution_listing = listing_template.format(contribution_id,
                                                                       contribution["first_name"],
                                                                       contribution["last_name"],
                                                                       contribution["title"])

                    except KeyError:

                        contribution_listing = "&mdash;"

                    template = '<div class="slotplan_cell"><span class="slotplan_hint">[{}] </span>{}</div>'

                    return_str += template.format(self.slotplanner_db["slot_dimension_names"][1 + level_1_index][level_2_index],
                                                  contribution_listing)
                
                # Close row
                #
                return_str += '<div class="clear"></div></div>'

            # Close table
            #
            return_str += '</div>'

        if(swap):

            return_str += '<input type="submit" value="Swap contributions"></form>'
        
        return return_str

    def render_kwargs(self, kwargs):
        """Return an HTML representation of the kwargs.
        """

        return_string = '<p><pre>{}</pre></p>'.format(str(kwargs).replace(", ", ",\n"))

        return return_string

    def menu(self):
        """Return HTML for a menu, with contents depending on the login status.
        """

        menu_html = '<ul class="menu">'

        menu_html += '<li><a href="/">Slotplan&nbsp;Home</a></li>'

        menu_html += '<li> <a href="/submit">Submit&nbsp;your&nbsp;contribution</a></li>'
        
        menu_html += '<li> <a href="/admin">Admin</a></li>'

        if cherrypy.session.get("logged_in"):

            menu_html += '<li> <a href="/slots">Edit&nbsp;slots</a></li>'

            menu_html += '<li> <a href="/schedule">Schedule&nbsp;contributions</a></li>'

            menu_html += '<li> <a href="/swap">Swap&nbsp;contributions</a></li>'

            menu_html += '<li> <a href="/logout">Log&nbsp;out</a></li>'

        menu_html += '</ul>'

        return menu_html

    def scheduled_contributions(self):
        """Return a list of contribution identifiers of already scheduled contributions.
        """
       
        scheduled_contributions = []

        if len(self.slotplanner_db["schedule"]):

            for level_2_items in self.slotplanner_db["schedule"].values():

                for level_3_items in level_2_items.values():

                    # TODO: This blindly assumes level 3 is the final level.
                    #
                    for identifier in level_3_items.values():

                        scheduled_contributions.append(identifier)
        
        return scheduled_contributions

    def replace_scheduled_contribution(self, old_id, new_id):
        """Replace contribution with old_id by the contribution with the new_id in the schedule.
        """

        if len(self.slotplanner_db["schedule"]):

            for level_2_items in self.slotplanner_db["schedule"].values():

                for level_3_items in level_2_items.values():

                    # TODO: This blindly assumes level 3 is the final level.
                    #
                    for level_3_key in level_3_items.keys():

                        if level_3_items[level_3_key] == old_id:

                            level_3_items[level_3_key] = new_id

        return

    def submit(self,
               first_name = None,
               last_name = None,
               email = None,
               twitter_handle = None,
               title = None,
               abstract = None):
        """Display the contribution submission form, or handle a submission.
        """

        page = simple.html.Page("Submit a Contribution", css = self.config["page_css"] + MENU_CSS)

        page.append(self.config["page_header"])

        page.append(self.menu())

        page.append('<h1>Slotplan for {}</h1>'.format(self.config["event"]))

        if (not first_name) and (not last_name) and (not email) and (not twitter_handle) and (not title) and (not abstract):
        
            page.append('<h2>Submit a Contribution</h2>')

            form = simple.html.Form("/submit", "POST")

            form.add_fieldset("About you")

            form.add_input("Your first name:", "text", "first_name")
            form.add_input("Your last name:", "text", "last_name")
            form.add_input("Email address you signed up with*:", "text", "email")
            form.add_input("Your Twitter handle (optional):", "text", "twitter_handle")

            form.add_fieldset("Contribution Title")
            form.add_textarea("title")

            form.add_fieldset("Contribution Abstract (optional)")
            form.add_textarea("abstract")

            page.append(str(form))

            page.append('<p>*Your email address is required to verify that you are signed up for the event. We will never give it to anyone else.</p>')

            page.append('<p>Questions? Email <a href="mailto:{0}">{0}</a></p>'.format(self.config["contact_email"]))

        elif first_name.strip() == "":

            page.append('<p><strong>Please enter your first name.</strong></p><p>Use the &quot;back&quot; button of your browser to go back.</p>')

        elif last_name.strip() == "":

            page.append('<p><strong>Please enter your last name.</strong></p><p>Use the &quot;back&quot; button of your browser to go back.</p>')

        # At least "a@b.c"
        #
        elif (len(email) < 5) or (email.find("@") < 1) or (email.find(".") < 1):

            page.append('<p><strong>I am sorry, but that does not look like a valid email address.</strong></p><p>Use the &quot;back&quot; button of your browser to go back.</p>')

        elif email.strip().lower() not in [participant_email.lower() for participant_email in self.config["participants_emails"]]:

            page.append('<p><strong>I am sorry, but i looks like you did not sign up for the event with that email address.</strong></p><p>Use the &quot;back&quot; button of your browser to go back and enter the email address you signed up with.</p><p>Questions? Email <a href="mailto:{0}">{0}</a></p>'.format(self.config["contact_email"]))
            
        elif title.strip() == "":

            page.append('<p><strong>Please enter the title of your contribution.</strong></p><p>Use the &quot;back&quot; button of your browser to go back.</p>')

        else:

            if twitter_handle.strip() and (not twitter_handle.startswith("@")):

                twitter_handle = "@" + twitter_handle.strip()

            contribution = {"first_name": first_name.strip(),
                            "last_name": last_name.strip(),
                            "email": email.strip(),
                            "twitter_handle": twitter_handle,
                            "title": title.strip(),
                            "abstract": abstract.strip()
                           }
            
            # Check whether this submission is JSON-serializable
            #
            try:

                json.dumps(contribution,
                           indent = 4,
                           sort_keys = True)
                
            except:

                # Possibly an encoding problem.
                #
                try:
                    if type(contribution["title"]) == bytes:
                        
                        contribution["title"] = codecs.decode(title.strip(),
                                                              "utf-8",
                                                              "replace")

                    if type(contribution["abstract"]) == bytes:
                        
                        contribution["abstract"] = codecs.decode(abstract.strip(),
                                                                 "utf-8",
                                                                 "replace")

                    json.dumps(contribution,
                               indent = 4,
                               sort_keys = True)
                    
                except:

                    # Giving up.

                    page.append('<p><strong>Your submission contains data that I can not save.</strong></p><p>It is my fault that I can not save it, but I need your help to fix it. Sorry. Please use the &quot;back&quot; button of your browser to go back and fix the data. Try to omit the abstract if you entered one.</p><p>Questions? Email <a href="mailto:{0}">{0}</a></p>'.format(self.config["contact_email"]))

                    page.append(self.config["page_footer"])

                    return str(page)
                
            # Contribution IDs are integers converted to strings,
            # for JSON compatibility. Still, we want to find the
            # highest ID and add 1 for the new one.
            #
            # To stay in line with Python's way of counting,
            # all IDs start at "0".
            #
            new_contribution_id = "0"

            if len(self.slotplanner_db["contributions"]) > 0:

                highest_id = int(new_contribution_id)

                for existing_id in self.slotplanner_db["contributions"].keys():

                    if int(existing_id) > highest_id:

                        highest_id = int(existing_id)

                new_contribution_id = str(highest_id + 1)

            self.slotplanner_db["contributions"][new_contribution_id] = contribution

            self.write_db()

            self.write_log("{} submitted contribution {}".format(email.strip(), new_contribution_id))

            subject = "[slotplanner] New submission by {} {}".format(first_name, last_name)

            body ="""Hi,

a new contribution has been submitted!

Name:
{} {}

Twitter handle:
{}

Title:
{}

Thanks for considering,
            your friendly slotplanner software :-)

-- 
Sent by slotplanner v{} configured for "{}"
""".format(first_name.strip(), last_name.strip(), twitter_handle.strip(), title.strip(), VERSION, self.config["event"])
            
            simple.email.send_threaded(self.config["email_sender"],
                                       self.config["email_recipients"],
                                       subject,
                                       body,
                                       self.config["email_host"],
                                       self.config["email_user"],
                                       self.config["email_password_rot13"])

            page.append('<p>Your submission has <strong>successfully been saved</strong>, you are done here. Thanks a ton!</p><p>Note: your contribution will <em>not</em> immediately be visiple in the slot plan. Please be patient.</p>')

        page.append(self.config["page_footer"])

        return str(page)

    submit.exposed = True

    def info(self, **kwargs):
        """Display live track information.
           Call info(level_1 = n, level_2 = m, level_3 = k, ...)
        """

        page = simple.html.Page("Track Information", css = self.config["page_css"])

        # NOTE: Only displaying info for scheduled events
        #
        if not ("level_1" in kwargs.keys()
                and kwargs["level_1"] in self.slotplanner_db["schedule"].keys()):

            scheduled_level_1 = list(self.slotplanner_db["schedule"].keys())

            scheduled_level_1.sort()

            for level_1_key in scheduled_level_1:

                link_template = '<p><a href="/info?level_1={}">{}</a></p>'

                page.append(link_template.format(level_1_key,
                                                 self.slotplanner_db["slot_dimension_names"][0][int(level_1_key)]))

            return str(page)

        elif not ("level_2" in kwargs.keys()
                  and kwargs["level_2"] in self.slotplanner_db["schedule"][kwargs["level_1"]].keys()):

            scheduled_level_2 = list(self.slotplanner_db["schedule"][kwargs["level_1"]].keys())

            scheduled_level_2.sort()

            for level_2_key in scheduled_level_2:

                link_template = '<p><a href="/info?level_1={}&level_2={}">{}</a></p>'

                page.append(link_template.format(kwargs["level_1"],
                                                 level_2_key,
                                                 self.slotplanner_db["slot_dimension_names"][1 + int(kwargs["level_1"])][int(level_2_key)]))

            return str(page)

        page.append('<h1>{}, {}</h1>'.format(self.slotplanner_db["slot_dimension_names"][0][int(kwargs["level_1"])],
                                             self.slotplanner_db["slot_dimension_names"][1 + int(kwargs["level_1"])][int(kwargs["level_2"])]))

        current_time = datetime.datetime.now()

        time_str = '{:02}:{:02}'.format(current_time.hour, current_time.minute)
        #REMOVE
        #time_str = "07:01"

        page.append('<p>{}</p>'.format(time_str))

        level_3_name_index_id = {}

        for index_id in self.slotplanner_db["schedule"][kwargs["level_1"]][kwargs["level_2"]].items():

            level_3_name_index_id[self.slotplanner_db["slot_dimension_names"][1 + len(self.slotplanner_db["slot_dimension_names"][0]) + int(kwargs["level_1"])][int(index_id[0])]] = index_id

        level_3_names = list(level_3_name_index_id.keys())

        level_3_names.sort(reverse = True)

        next_name = None

        for name in level_3_names:

            # NOTE: Comparing HH:MM as strings should work out alright
            #
            if name > time_str:

                next_name = name

        next_contribution = '&mdash;'
        parallel_contributions = []

        if next_name is not None:
            
            contribution = self.slotplanner_db["contributions"][level_3_name_index_id[next_name][1]]
                
            next_contribution = '{} {} {}: <em>{}</em>'.format(next_name,
                                                               contribution["first_name"],
                                                               contribution["last_name"],
                                                               contribution["title"])

            for level_2_index in self.slotplanner_db["schedule"][kwargs["level_1"]]:

                if level_2_index != kwargs["level_2"]:

                    for level_3_index in self.slotplanner_db["schedule"][kwargs["level_1"]][level_2_index].keys():

                        if level_3_index == level_3_name_index_id[next_name][0]:

                            contribution = self.slotplanner_db["contributions"][self.slotplanner_db["schedule"][kwargs["level_1"]][level_2_index][level_3_index]]

                            contribution_template = '<dt>{}</dt><dd>{} {} {}: <em>{}</em></dd>'
                
                            parallel_contributions.append(contribution_template.format(self.slotplanner_db["slot_dimension_names"][1 + int(kwargs["level_1"])][int(level_2_index)],
                                                                                       next_name,
                                                                                       contribution["first_name"],
                                                                                       contribution["last_name"],
                                                                                       contribution["title"]))
                            
        page.append('<p>Next:<br>{}</p>'.format(next_contribution))

        parallel_list = ''.join(parallel_contributions)

        parallel_list = '<dl>{}</dl>'.format(parallel_list)

        page.append('<p>Parallel:</p>{}'.format(parallel_list))

        page.append('<p><a href="/info">Track overview &gt;&gt;</a></p>')
        
        return str(page)

    info.exposed = True

    def login(self, password = None):
        """If called without arguments, return a login form.
           If called with arguments, try to log in.
        """

        page = simple.html.Page("Log in", css = self.config["page_css"] + MENU_CSS)

        page.append(self.config["page_header"])

        # Password can not be empty
        #
        if (not password) or (password != self.config["admin_password"]):

            page.append(self.menu())

            page.append('<h1>Log In</h1>')

            form = simple.html.Form("/login", "POST", submit_label = "Let me in!")

            form.add_input("Password: ", "password", "password")

            page.append(str(form))

        else:
            cherrypy.session["logged_in"] = True

            page.append(self.menu())

            page.append('<h1>Log In</h1>')

            page.append('<p>You are now logged in.</p>')

        page.append(self.config["page_footer"])

        return str(page)

    login.exposed = True

    @logged_in
    def admin(self, password = None):
        """Slotplan administration interface.
        """

        page = simple.html.Page("Admin", css = self.config["page_css"] + MENU_CSS)

        page.append(self.config["page_header"])

        page.append(self.menu())

        page.append('<h1>Slotplan Admin Page</h1>')

        page.append('<h2><a name="toc"></a>Submitted Contributions</h2>')

        contribution_ids = list(self.slotplanner_db["contributions"].keys())

        # IDs are string-representations of integers, but need
        # to be sorted as the latter
        #
        contribution_ids = [int(id_str) for id_str in contribution_ids]
        
        contribution_ids.sort(reverse = True)

        contribution_ids = [str(id_int) for id_int in contribution_ids]

        # Table of contents
        #
        page.append('<ul>')

        toc_template = '<li style="line-height:150%;"><a href="#{0}">[{0}] {1} {2}: <em>{3}</em></a></li>'
        
        for contribution_id in contribution_ids:

            contribution = self.slotplanner_db["contributions"][contribution_id]

            page.append(toc_template.format(contribution_id,
                                            contribution["first_name"],
                                            contribution["last_name"],
                                            contribution["title"]))
            
        page.append('</ul>')

        # Actual contributions list
        #
        contribution_template = '<p style="line-height:130%;"><a name="{5}"></a>{0} {1} &lt;<a href="mailto:{2}">{2}</a>&gt;, Twitter: <a href="https://twitter.com/{3}">{3}</a><br>Title: &quot;{4}&quot;<br>[ID: {5}]</p>'

        for contribution_id in contribution_ids:

            contribution = self.slotplanner_db["contributions"][contribution_id]

            page.append(contribution_template.format(contribution["first_name"],
                                                     contribution["last_name"],
                                                     contribution["email"],
                                                     contribution["twitter_handle"],
                                                     contribution["title"],
                                                     contribution_id))

            if contribution["abstract"]:

                page.append('<p style="font-size:80%;">{}</p>'.format(contribution["abstract"]))

            page.append('<p><a href="#toc">&uarr; Up to table of contents</a></p><hr>')

        page.append(self.config["page_footer"])

        return str(page)

    admin.exposed = True

    @logged_in
    def slots(self, **kwargs):
        """Display a form to enter slot dimensions, or process a slot dimension edit.
        """
        
        page = simple.html.Page("Edit Slot Dimensions", css = self.config["page_css"] + MENU_CSS)

        page.append(self.config["page_header"])

        page.append(self.menu())

        page.append('<h1>Edit Slot Dimensions</h1>')

        page.append('<p>Here you can enter up to {} level-1 elements, along with their sublevels.</p>'.format(LEVEL_1_ELEMENTS))

        page.append('''<p>That sounds abtract because it tries to be open to a lot of applications.
                       Typical levels would be</p>
                       <ul>
                       <li><em>Wednesday</em>, <em>Thursday</em> for level 1,</li>
                       <li><em>Room A</em>, <em>Room B</em> for level 2</li>
                       <li>and <em>10:00</em>, <em>11:00</em>, <em>14:00</em> for level 3.</li>
                       </ul>''')

        page.append('<p>If you need more than {} elements in level 1, you will have to edit the JSON file directly.</p>'.format(LEVEL_1_ELEMENTS))

        page.append('<p><strong>Warning:</strong> What ever you submit <strong>will replace all existing slot dimensions and their labels</strong>.</p>')

        # When called with arguments, expect a slot dimension names
        # update, read input and save it.
        #
        if len(kwargs):

            slot_dimension_names = []

            # Only change anything existing when there is at least
            # an element_1
            #
            if "element_1" in kwargs.keys() and kwargs["element_1"].strip():

                level_1 = []
                
                for i in range(1, LEVEL_1_ELEMENTS + 1):

                    # TODO: This will append the 3rd element as 2nd if the 2nd is omitted
                    #
                    if "element_{}".format(i) in kwargs.keys() and kwargs["element_{}".format(i)].strip():

                        level_1.append(kwargs["element_{}".format(i)].strip())

                levels_2_3 = []

                for i in range(2, LEVEL_1_ELEMENTS + 1):
                
                    # Get the respective next levels from the actual
                    # length of the submitted levels, not by parsing the
                    # names of the arguments.
                    #
                    # Each level 1 has an independent level 2 and level 3
                    # subdivision. But the level 3 subdivision is the same
                    # for all level 2 elements of a level 1 element.
                    #
                    for j in range(1, len(level_1) + 1):

                        next_level = []

                        if ("element_{}_dimension_{}".format(j, i) in kwargs.keys()
                            and kwargs["element_{}_dimension_{}".format(j, i)].strip()
                            and kwargs["element_{}_dimension_{}".format(j, i)].strip() != "Enter level {} elements here, one per line".format(i)):

                            # Expecting a newline-separated list

                            next_level = kwargs["element_{}_dimension_{}".format(j, i)].strip().split("\n")

                            next_level = [s.strip() for s in next_level if s.strip()]

                        levels_2_3.append(next_level)

                # Concatenate everything collected so far
                #
                slot_dimension_names.append(level_1)

                for l in levels_2_3:

                    slot_dimension_names.append(l)

                # Now store everything in the database and sync to file
                #
                self.slotplanner_db["slot_dimension_names"] = slot_dimension_names

                self.write_db()

                self.write_log("Slot dimension names have been updated.")

        form = simple.html.Form("/slots", "POST", submit_label = "Submit and replace existing")

        # Display slot dimension names form, displaying present
        # level lables if available.
        #
        for i in range(1, LEVEL_1_ELEMENTS + 1):

            form.add_fieldset("Level 1 Element {}".format(i))

            default_level_1 = ""
            default_level_2 = "Enter level 2 elements here, one per line"
            default_level_3 = "Enter level 3 elements here, one per line"
            
            if (self.slotplanner_db["slot_dimension_names"]
                and len(self.slotplanner_db["slot_dimension_names"][0])
                and i <= len(self.slotplanner_db["slot_dimension_names"][0])):

                default_level_1 = self.slotplanner_db["slot_dimension_names"][0][i - 1]

                if (1 + i <= len(self.slotplanner_db["slot_dimension_names"])
                    and len(self.slotplanner_db["slot_dimension_names"][0 + i])):

                    default_level_2 = "\n".join(self.slotplanner_db["slot_dimension_names"][0 + i])

                    if (1 + len(self.slotplanner_db["slot_dimension_names"][0]) + i <= len(self.slotplanner_db["slot_dimension_names"])
                        and len(self.slotplanner_db["slot_dimension_names"][0 + len(self.slotplanner_db["slot_dimension_names"][0]) + i])):

                        default_level_3 = "\n".join(self.slotplanner_db["slot_dimension_names"][0 + len(self.slotplanner_db["slot_dimension_names"][0]) + i])

            form.add_input("Level 1 Element {} name: ".format(i),
                           "text",
                           "element_{}".format(i),
                           value = default_level_1)

            form.add_textarea("element_{}_dimension_2".format(i),
                              content = default_level_2)

            form.add_textarea("element_{}_dimension_3".format(i),
                              content = default_level_3)

        page.append(str(form))

        page.append(self.config["page_footer"])

        return str(page)

    slots.exposed = True

    @logged_in
    def schedule(self, **kwargs):
        """Display a form to schedule contributions, or process a scheduling request.
        """

        page = simple.html.Page("Schedule Contributions", css = self.config["page_css"] + MENU_CSS)

        page.append(self.config["page_header"])

        page.append(self.menu())

        page.append('<h1>Schedule Contributions</h1>')

        if not len(self.slotplanner_db["slot_dimension_names"]):

            page.append('<p><strong>No slot dimensions have been configured.</strong> To schedule contributions, please <a href="/slots">configure slot dimensions</a>.</p>')

            page.append(self.config["page_footer"])

            return str(page)

        # It would be much more elegant to handle all list element
        # references by index. But it is tricky to build an HTML form
        # that displays the verbose label, but submits an index.

        if ("contribution" in kwargs.keys()
            and "level_1" in kwargs.keys()
            and "level_2" in kwargs.keys()
            and "level_3" in kwargs.keys()):
            
            contribution_id = kwargs["contribution"].strip("[").split("]")[0]
            index_level_1 = int(kwargs["level_1"])
            len_level_1 = len(self.slotplanner_db["slot_dimension_names"][0])

            if (contribution_id in self.slotplanner_db["contributions"].keys()
                and index_level_1 <= len_level_1
                and 1 + index_level_1 <= len(self.slotplanner_db["slot_dimension_names"])
                and 1 + len_level_1 + index_level_1 <= len(self.slotplanner_db["slot_dimension_names"])
                and kwargs["level_2"] in self.slotplanner_db["slot_dimension_names"][1 + index_level_1]
                and kwargs["level_3"] in self.slotplanner_db["slot_dimension_names"][1 + len_level_1 + index_level_1]):

                index_level_2 = str(self.slotplanner_db["slot_dimension_names"][1 + index_level_1].index(kwargs["level_2"]))
                index_level_3 = str(self.slotplanner_db["slot_dimension_names"][1 + len_level_1 + index_level_1].index(kwargs["level_3"]))

                # For JSON compatibility, keys are handled as strings.
                #
                index_level_1 = str(index_level_1)

                try:
                    self.slotplanner_db["schedule"][index_level_1][index_level_2][index_level_3] = contribution_id

                except KeyError:

                    try:
                        self.slotplanner_db["schedule"][index_level_1][index_level_2] = {index_level_3: contribution_id}

                    except KeyError:

                        self.slotplanner_db["schedule"][index_level_1] = {index_level_2: {index_level_3: contribution_id}}

                # Now sync to file
                #
                self.write_db()

                self.write_log("Contribution {} has been scheduled.".format(contribution_id))

                page.append('<p>Contribution {} has been scheduled. Thanks for submitting!</p>'.format(contribution_id))

        # Display forms to schedule a contribution

        page.append('<p>Note: scheduling a contribution will <strong>silently replace</strong> any contribution already scheduled for the slot.</p>')

        # Only display contributions that are not yet scheduled
        #
        contribution_ids = [identifier for identifier in self.slotplanner_db["contributions"].keys() if identifier not in self.scheduled_contributions()]

        if not len(contribution_ids):
        
            page.append('<p><strong>There are no unscheduled contributions left.</strong></p>')

            page.append(self.config["page_footer"])

            return str(page)
        
        # TODO: Duplicated from admin()
        #
        # IDs are string-representations of integers, but need
        # to be sorted as the latter
        #
        contribution_ids = [int(id_str) for id_str in contribution_ids]
        
        contribution_ids.sort()

        contribution_ids = [str(id_int) for id_int in contribution_ids]

        template = '[{0}] {1} {2}: {3}'

        contributions = [template.format(contribution_id,
                                         self.slotplanner_db["contributions"][contribution_id]["first_name"],
                                         self.slotplanner_db["contributions"][contribution_id]["last_name"],
                                         self.slotplanner_db["contributions"][contribution_id]["title"])
                         for contribution_id in contribution_ids]

        for i in range(len(self.slotplanner_db["slot_dimension_names"][0])):
        
            form = simple.html.Form("/schedule",
                                    "POST",
                                    submit_label = "Schedule and replace for {}".format(self.slotplanner_db["slot_dimension_names"][0][i]))

            form.add_fieldset(self.slotplanner_db["slot_dimension_names"][0][i])

            form.add_hidden("level_1", str(i))

            # It would be much more elegant to handle all list element
            # references by index. But it is tricky to build an HTML form
            # that displays the verbose label, but submits an index.

            form.add_drop_down_list("",
                                    "contribution",
                                    contributions)

            form.add_drop_down_list("",
                                    "level_2",
                                    self.slotplanner_db["slot_dimension_names"][i + 1])

            form.add_drop_down_list("",
                                    "level_3",
                                    self.slotplanner_db["slot_dimension_names"][i + 1 + len(self.slotplanner_db["slot_dimension_names"][0])])

            page.append(str(form))
            
        page.append(self.config["page_footer"])

        return str(page)

    schedule.exposed = True

    @logged_in
    def swap(self, swap = None):
        """Display a slotplan table with the option to swap elements, or process a swap.
        """

        page = simple.html.Page("Swap Contributions", css = self.config["page_css"] + SLOTPLAN_TABLE_CSS + MENU_CSS)

        page.append(self.config["page_header"])

        page.append(self.menu())

        page.append('<h1>Swap Contributions</h1>')

        if swap is not None:

            if not type(swap) == list:

                page.append('<p><strong>Please select two contributions to swap.</strong></p>')

            elif len(swap) > 2:

                page.append('<p>{} contributions selected. <strong>Please select no more than two contributions to swap.</strong></p>'.format(len(swap)))

            elif not (swap[0] in self.scheduled_contributions()
                      and swap[1] in self.scheduled_contributions()):

                page.append('<p><strong>I could not find all contributions to swap in the schedule.</strong></p>')

            else:

                # NOTE: We need to make sure at no point the same contribution is scheduled twice.
                #
                self.replace_scheduled_contribution(swap[0], "REPLACEMENT_MARK")

                self.replace_scheduled_contribution(swap[1], swap[0])

                self.replace_scheduled_contribution("REPLACEMENT_MARK", swap[1])

                # Now sync to file
                #
                self.write_db()

                self.write_log('Swapped contributions {} and {}'.format(swap[0], swap[1]))

                page.append('<p><strong>Successfully swapped contributions {} and {}.</strong></p>'.format(swap[0], swap[1]))
                
        page.append(self.render_slotplan(swap = True))
            
        page.append(self.config["page_footer"])
        
        return str(page)

    swap.exposed = True

    def logout(self):
        """Expire the current Cherrypy session for this user.
        """

        if cherrypy.session.get("logged_in"):

            cherrypy.lib.sessions.expire()

        page = simple.html.Page("Access restricted", css = self.config["page_css"] + MENU_CSS)

        page.append(self.config["page_header"])

        page.append(self.menu())

        page.append('<p>You are logged out.</p>')

        page.append(self.config["page_footer"])

        return str(page)

    logout.exposed = True

def main():
    """Main function, for IDE convenience.
    """

    root = SlotplannerWebApp()

    config_dict = {"/" : {"tools.sessions.on" : True,
                          "tools.sessions.timeout" : 60},
                   "global" : {"server.socket_host" : "127.0.0.1",
                               "server.socket_port" : root.config["server_port"],
                               "server.thread_pool" : root.config["server_threads"]}}

    # Conditionally turn off Autoreloader
    #
    if not AUTORELOAD:

        cherrypy.engine.autoreload.unsubscribe()

    cherrypy.quickstart(root, config = config_dict)

    return

if __name__ == "__main__":

    main()
