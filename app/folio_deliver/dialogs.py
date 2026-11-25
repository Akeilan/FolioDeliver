"""Small dialogs: messages, save prompts, text prompts."""
from gi.repository import Gtk

from . import APP_NAME


class Dialogs:
    def __init__(self, win):
        self.win = win

    def _dialog(self, title):
        d = Gtk.Dialog(title=title, transient_for=self.win, modal=True)
        d.get_style_context().add_class("folio-dialog")
        d.set_resizable(False)
        return d

    def message(self, text, title=APP_NAME):
        d = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.WARNING,
                              buttons=Gtk.ButtonsType.OK, text=text)
        d.set_title(title)
        d.run()
        d.destroy()

    def info(self, text, title=APP_NAME):
        d = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.INFO,
                              buttons=Gtk.ButtonsType.OK, text=text)
        d.set_title(title)
        d.run()
        d.destroy()

    def confirm_save(self, name):
        """Save / Don't Save / Cancel → 'save' | 'discard' | 'cancel'."""
        d = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.QUESTION,
                              text="Want to save your changes to '%s'?" % name)
        d.set_title(APP_NAME)
        d.add_button("Save", 1)
        d.add_button("Don't Save", 2)
        d.add_button("Cancel", 3)
        d.set_default_response(1)
        r = d.run()
        d.destroy()
        return {1: "save", 2: "discard"}.get(r, "cancel")

    def recovered(self, items):
        """[(name, time)] an earlier run left unsaved: 'open' | 'discard' | 'later'."""
        import datetime
        d = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.QUESTION,
                              text="Folio Show closed before %s saved." % ("this presentation was" if len(items) == 1
                                                                           else "these presentations were"))
        lines = ["%s — kept %s" % (n, datetime.datetime.fromtimestamp(t).strftime("%-d %b, %H:%M")) for n, t in items]
        d.format_secondary_text("\n".join(lines[:10]) + ("\n…" if len(lines) > 10 else "") +
                                "\n\nOpen the copies AutoRecover kept? They open unsaved, to save where you like.")
        d.set_title(APP_NAME)
        d.add_button("Not Now", 3)
        d.add_button("Delete Them", 2)
        d.add_button("Open", 1)
        d.set_default_response(1)
        r = d.run()
        d.destroy()
        return {1: "open", 2: "discard"}.get(r, "later")

    def changed_on_disk(self, name):
        """The file was saved by another program since it was opened (S12-07):
        'overwrite' | 'copy' | 'cancel'."""
        d = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.WARNING,
                              text="'%s' was changed by another program since you opened it." % name)
        d.format_secondary_text("Saving now replaces those changes. Save a copy under another name to keep both.")
        d.set_title(APP_NAME)
        d.add_button("Cancel", 3)
        d.add_button("Save a Copy…", 2)
        d.add_button("Replace Their Changes", 1)
        d.set_default_response(2)
        r = d.run()
        d.destroy()
        return {1: "overwrite", 2: "copy"}.get(r, "cancel")

    def ask_password(self, title, label):
        """A password (typed hidden), or None."""
        d = self._dialog(title)
        d.add_button("OK", Gtk.ResponseType.OK)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.set_default_response(Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.set_border_width(10)
        box.set_spacing(6)
        box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
        e = Gtk.Entry(visibility=False)
        e.set_activates_default(True)
        box.pack_start(e, False, False, 0)
        d.entry = e
        d.show_all()
        r = d.run()
        t = e.get_text()
        d.destroy()
        return t if r == Gtk.ResponseType.OK else None

    def ask_text(self, title, label, value=""):
        d = self._dialog(title)
        d.add_button("OK", Gtk.ResponseType.OK)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.set_default_response(Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.set_border_width(10)
        box.set_spacing(6)
        box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
        e = Gtk.Entry()
        e.set_text(value)
        e.set_activates_default(True)
        box.pack_start(e, False, False, 0)
        d.show_all()
        r = d.run()
        t = e.get_text()
        d.destroy()
        return t if r == Gtk.ResponseType.OK else None
