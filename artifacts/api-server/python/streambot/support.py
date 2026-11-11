"""Support entry points. Conversations now run through tickets (tickets.py / ticket_bot.py);
this module keeps /myid and the contact text, and routes the old commands to the ticket flow."""


class SupportRelay:
    def __init__(self,bot):
        self.bot=bot;self.store=bot.store;self.config=bot.service.config

    @property
    def admin(self):return self.config.get('support_admin_id')

    def contact_text(self):
        return self.config.get('support','Contact support.')+'\n'+self.config['support_url']

    def handle(self,message,command,argument=''):
        uid=message['from']['id']
        if command=='/myid':
            self.bot.send(uid,'Your Telegram user ID is: '+str(uid));return True
        return self.bot.tickets.message(message,command,argument)
