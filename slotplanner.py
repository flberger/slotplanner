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

VERSION = "0.1.0"

LOGGER = logging.getLogger("slotplanner")
LOGGER.setLevel(logging.DEBUG)
STDERR_FORMATTER = logging.Formatter("slotplanner [{levelname}] {funcName}(): {message} (l.{lineno})", style = "{")
STDERR_HANDLER = logging.StreamHandler()
STDERR_HANDLER.setFormatter(STDERR_FORMATTER)
LOGGER.addHandler(STDERR_HANDLER)

PORT = 8311
THREADS = 4
AUTORELOAD = False

# Make HTML textareas more compact
#
simple.html.ROWS = 8


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
               [FIRST_1, FIRST_2],
               [SECOND_1, SECOND_2],
               ...
           ],
       "schedule":
           {INDEX_FIRST_1_AS_STRING:
               {INDEX_SECOND_1_AS_STRING: CONTRIBUTION_ID_STRING,
                INDEX_SECOND_2_AS_STRING: CONTRIBUTION_ID_STRING,
                ...
               },
            INDEX_FIRST_2_AS_STRING:
               {INDEX_SECOND_1_AS_STRING: CONTRIBUTION_ID_STRING,
                INDEX_SECOND_2_AS_STRING: CONTRIBUTION_ID_STRING,
                ...
               },
            ...
           }
       }
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
                                  'admin_password = "admin"'
                                 ]

                f.write("\n".join(config_options) + "\n")

            raise
            
        # Make self.__call__ visible to cherrypy
        #
        self.exposed = True

        return

    def __call__(self):
        """Called by cherrypy for the / root page.
        """

        page = simple.html.Page("slotplanner - {}".format(self.config["event"]), css = self.config["page_css"])

        page.append(self.config["page_header"])

        page.append('<h1>Slotplan for {}</h1>'.format(self.config["event"]))

        page.append('<p><a href="/submit">Submit your contribution &gt;&gt;</a></p>')

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

        self.slotplanner_db["slot_dimension_names"].append(["Monday", "Tuesday"])
        self.slotplanner_db["slot_dimension_names"].append(["Room 1", "Room 2"])
        self.slotplanner_db["slot_dimension_names"].append(["Morning", "Afternoon"])

        self.slotplanner_db["schedule"]["0"] = {"0": {"1": "123"}}

        self.write_db()

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

        page = simple.html.Page("Submit a Contribution", css = self.config["page_css"])

        page.append(self.config["page_header"])

        page.append('<h1>Slotplan for {}</h1>'.format(self.config["event"]))

        if (not first_name) and (not last_name) and (not email) and (not twitter_handle) and (not title) and (not abstract):
        
            page.append('<h2>Submit a Contribution</h2>')

            page.append('<p><a href="/">&lt;&lt; Back to slotplan home page</a></p>')

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

            page.append('<p><a href="/">&lt;&lt; Back to slotplan home page</a></p>')

        page.append(self.config["page_footer"])

        return str(page)

    submit.exposed = True

    def admin(self, password = None):
        """Slotplan administration interface.
        """

        page = simple.html.Page("Admin", css = self.config["page_css"])

        page.append(self.config["page_header"])

        page.append('<h1>Slotplan Admin Page</h1>')

        page.append('<p><a href="/">&lt;&lt; Back to slotplan home page</a></p>')

        # Admin passwort can not be empty
        #
        if (not password) or (password != self.config["admin_password"]):

            form = simple.html.Form("/admin", "POST", submit_label = "Let me in!")

            form.add_input("Password: ", "password", "password")

            page.append(str(form))

            page.append(self.config["page_footer"])

            return str(page)

        page.append('<h2>Submitted Contributions</h2>')

        contribution_template = '<p style="line-height:130%;">{0} {1} &lt;<a href="mailto:{2}">{2}</a>&gt;, Twitter: <a href="https://twitter.com/{3}">{3}</a><br>Title: &quot;{4}&quot;<br>[ID: {5}]</p>'

        contribution_ids = list(self.slotplanner_db["contributions"].keys())

        contribution_ids.sort()

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

            page.append('<hr>')

        page.append(self.config["page_footer"])

        return str(page)

    admin.exposed = True
    
def main():
    """Main function, for IDE convenience.
    """

    root = SlotplannerWebApp()

    config_dict = {"/" : {"tools.sessions.on" : True,
                          "tools.sessions.timeout" : 60},
                   "global" : {"server.socket_host" : "127.0.0.1",
                               "server.socket_port" : PORT,
                               "server.thread_pool" : THREADS}}

    # Conditionally turn off Autoreloader
    #
    if not AUTORELOAD:

        cherrypy.engine.autoreload.unsubscribe()

    cherrypy.quickstart(root, config = config_dict)

    return

if __name__ == "__main__":

    main()
