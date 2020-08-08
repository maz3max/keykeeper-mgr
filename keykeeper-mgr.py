#!/usr/bin/env python3

import urwid
import time
import threading
import os
import fcntl

lipsum = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."



class KeyKeeperManagerDummyLogic:
    def __init__(self, central_status_pipe, coin_status_pipe):
        self.central_status_pipe = central_status_pipe
        self.coin_status_pipe = coin_status_pipe
        self.ready = threading.Event()
        self.request_central_update = threading.Event()
        self.request_shutdown = threading.Event()

        self._usernames = ['Anna', 'Nicole', 'Luca', 'Melanie', 'Leon', 'Julia', 'Michelle', 'Tom', 'Lea', 'Tim', 'Lena', 'Michael', 'Stefanie', 'Lisa', 'Daniel', 'Christina', 'Hannah', 'Dennis', 'Jonas', 'Christian',
                           'Laura', 'Jannik', 'Sandra', 'Lukas', 'Julia', 'Nadine', 'Stefan', 'Martin', 'Jan', 'Sarah', 'Sabrina', 'Anja', 'Alexander', 'Thomas', 'Sebastian', 'Katrin', 'Lara', 'Niklas', 'Jan', 'Finn']

        def background_task(central_status_pipe, coin_status_pipe):
            # TODO use asyncIO scheduler for different tasks
            os.write(central_status_pipe, str(
                "status: connecting to central").encode('utf8'))
            time.sleep(1)
            os.write(central_status_pipe, str(
                "status: synchronizing database").encode('utf8'))
            time.sleep(0.2)
            os.write(central_status_pipe, str(
                "status: central connected and scanning").encode('utf8'))
            self.request_shutdown.wait()
            # time.sleep(5)
            # os.write(central_status_pipe, str(count).encode('utf8')) # that's how we can update the status message

        self.thread = threading.Thread(target=background_task, args=(central_status_pipe, coin_status_pipe))
        self.thread.start()

    def shutdown(self):
        self.request_shutdown.set()
    # consider this list read-only

    def get_usernames(self):
        return self._usernames
    # try to add user, return False if name is already taken

    def add_user(self, name):
        if name not in self._usernames:
            self._usernames.append(name)
            return True
        return False
    # try to remove user, return False if user is not found

    def remove_user(self, name):
        if name in self._usernames:
            self._usernames.remove(name)
            return True
        return False

    # try to write coin, writes status messages callback
    # this is blocking, we don't allow the user to fiddle around while
    # programming a chip
    # TODO: CORRECTION: for status updates, this cannot be blocking
    # TODO: move into background task
    def write_coin(self, name):
        if name not in self._usernames:
            # callback("writing coin FAILED, user cannot be found")
            return
        time.sleep(2)
        # callback("writing coin SUCCEEDED")

    def reset_coin(self, name, callback):
        time.sleep(2)
        # callback("resetting coin SUCCEEDED")

class QuestionBox(urwid.Filler):
    def __init__(self, questionstr, callback_confirm=None, callback_cancel=None,valign=urwid.widget.MIDDLE,
                height=('relative', 80), min_height=None, top=0, bottom=0):
        self.enter = callback_confirm
        super().__init__(urwid.ListBox([urwid.Edit(questionstr), urwid.AttrWrap(urwid.Button("nevermind.", callback_cancel),
                        'buttn', 'buttnf_deny'),]), valign=valign, height=height,
                        min_height=min_height, top=top, bottom=bottom)

    def keypress(self, size, key):
        if key == 'enter' and self.body.focus_position == 0:
            self.enter(self.body.body[0].edit_text)
        else:
            return super(QuestionBox, self).keypress(size, key)

class KeyKeeperManagerTUI:
    def __init__(self, app_logic):
        urwid.set_encoding('utf8')
        self.status = urwid.Text("status: connecting to central...")
        self.hint_text = urwid.Text("Hints will be displayed here")
        self.chosen_user = None

        def add_user(user_data):
            self.enter_name_prompt.top_w.base_widget.body[0].edit_text = ""
            self.enter_name_prompt.set_focus_path([1,0])
            self.loop.widget = self.enter_name_prompt

        def remove_user(user_data):
            self.choose_user_prompt = urwid.Overlay(
                urwid.LineBox(urwid.ListBox([
                    *[urwid.AttrWrap(urwid.Button(n, remove_user_chosen),
                                     'buttn', 'buttnf') for n in self.app_logic.get_usernames()],
                    urwid.AttrWrap(urwid.Button("back to menu", back_to_menu),
                                   'buttn', 'buttnf_deny'),
                ]), title="which user shall be removed?"),
                self.mainframe,
                'center', ('relative', 50),
                'middle', ('relative', 50))
            self.loop.widget = self.choose_user_prompt

        def remove_user_chosen(user_data):
            id = self.choose_user_prompt.top_w.base_widget.focus_position
            name = self.app_logic.get_usernames()[id]
            if self.app_logic.remove_user(name):
                self.hint_text.set_text("user [{}] has been deleted.".format(name))
            self.loop.widget = self.mainframe

        def write_coin(user_data):
            self.choose_user_prompt = urwid.Overlay(
                urwid.LineBox(urwid.ListBox([
                    *[urwid.AttrWrap(urwid.Button(n, write_coin_chosen),
                                     'buttn', 'buttnf') for n in self.app_logic.get_usernames()],
                    urwid.AttrWrap(urwid.Button("back to menu", back_to_menu),
                                   'buttn', 'buttnf_deny'),
                ]), title="whose coin shall be written?"),
                self.mainframe,
                'center', ('relative', 50),
                'middle', ('relative', 50))
            self.loop.widget = self.choose_user_prompt

        def write_coin_chosen(user_data):
            id = self.choose_user_prompt.top_w.base_widget.focus_position
            name = self.app_logic.get_usernames()[id]

            self.wait_prompt.top_w.base_widget.body[0].set_text("writing coin\n")
            self.loop.widget = self.wait_prompt
            self.app_logic.write_coin(name)
            self.loop.widget = self.mainframe
        def reset_coin(user_data):
            pass

        def username_entered(name):
            if name == "":
                return
            if self.app_logic.add_user(name):
                self.confirm_writing_prompt.top_w.base_widget.body[0] \
                    .set_text("user [{}] has been added.\n".format(name)
                              + "do you want to write their coin now?")
                self.loop.widget = self.confirm_writing_prompt
                self.confirm_writing_prompt.set_focus_path([1, 1])
                self.enter_name_prompt.top_w.base_widget.body[0].set_caption("")
                self.chosen_user = name
                self.hint_text.set_text("user [{}] has been added.".format(name))
            else:
                self.enter_name_prompt.top_w.base_widget.body[0].set_caption("this username is already taken!\n")

        def back_to_menu(user_data):
            self.loop.widget = self.mainframe

        actionpile = urwid.Pile([
            urwid.AttrWrap(urwid.Button(*b), 'buttn', 'buttnf') for b in [
                ("add user", add_user),
                ("remove user", remove_user),
                ("write coin", write_coin),
                ("reset coin", reset_coin)
            ]
        ])

        self.mainframe = urwid.Frame(
            urwid.Columns([
                ('fixed', 18, urwid.LineBox(urwid.Filler(actionpile))),
                ('weight', 1, urwid.LineBox((urwid.ListBox([
                    self.hint_text,
                ])))),
            ]),

            header=urwid.Text("keykeeper management utility, press q to exit"),
            footer=self.status,
        )

        self.enter_name_prompt = urwid.Overlay(
            urwid.LineBox(QuestionBox("", username_entered, back_to_menu),
                          title="what's the name of the new user?"),
            self.mainframe,
            'center', ('relative', 50),
            'middle', ('relative', 50), min_height=6)

        self.confirm_writing_prompt = urwid.Overlay(
            urwid.LineBox(urwid.ListBox([
                urwid.Text("PLACEHOLDER"),
                urwid.AttrWrap(urwid.Button("let's go!", None),
                               'buttn', 'buttnf_confirm'),
                urwid.AttrWrap(urwid.Button("nevermind.", back_to_menu),
                               'buttn', 'buttnf_deny'),
            ]), title="confirm writing"),
            self.mainframe,
            'center', ('relative', 50),
            'middle', ('relative', 50), min_height=6)

        self.wait_prompt = urwid.Overlay(
            urwid.LineBox(urwid.ListBox([
                urwid.Text("PLACEHOLDER"),
            ]), title="please wait"),
            self.mainframe,
            'center', ('relative', 50),
            'middle', ('relative', 50), min_height=6)
        self.choose_user_prompt = None

        def handle_key(key):
            if key == 'q':
                self.app_logic.shutdown()
                raise urwid.ExitMainLoop()

        self.loop = urwid.MainLoop(
            self.mainframe,
            palette=[
                ('buttn', 'default', 'default'),
                ('buttnf', 'standout', 'default'),
                ('buttnf_confirm', 'black', 'light green'),
                ('buttnf_deny', 'black', 'dark red'),
            ],
            handle_mouse=False,
            unhandled_input=handle_key)

        def handle_coin_status_update(data):
            msg = data.decode('utf8')
            text = self.wait_prompt.top_w.base_widget.body[0].get_text()[0] + msg
            self.wait_prompt.top_w.base_widget.body[0].set_text(text)
            if msg.startswith('done'):
                pass
                # TODO: add back-to-menu button to wait_prompt

        def handle_central_status_update(data):
            msg = data.decode('utf8')
            self.status.set_text(msg)
            
                
        self.central_status_pipe = self.loop.watch_pipe(handle_central_status_update)
        self.coin_status_pipe = self.loop.watch_pipe(handle_coin_status_update)
        self.app_logic = app_logic(self.central_status_pipe, self.coin_status_pipe)
        self.loop.run()


if __name__ == '__main__':
    KeyKeeperManagerTUI(KeyKeeperManagerDummyLogic)
