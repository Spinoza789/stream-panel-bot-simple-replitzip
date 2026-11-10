"""Customer-facing setup instructions shared by trials and memberships.

Every builder here returns Telegram HTML (parse_mode='HTML'); dynamic values are escaped."""
from html import escape

APP_DOWNLOAD_GUIDE = """<b>APP DOWNLOAD CODES</b>

Enter a code in the Downloader app (Firestick):
<b>Sky Live</b>
<code>2976199</code> • <code>565410</code> • <code>6261787</code>
<code>962396</code> • <code>969828</code>

<b>Magic</b>
<code>9801832</code>

<b>Safe Media</b>
<code>589666</code> • <code>7400092</code>

<b>iPhone/Apple TV App</b> - viziplayer.com/app
URL Code <code>BA896705</code>

<b>Android APPS</b>
Sky Live: https://tinyurl.com/256zmkh3
Sky Glass: https://bit.ly/uhdglass
Smarters: https://apk.st/HVJU
Magic: https://apk.st/VPYJV
Safe Media: https://tinyurl.com/4fevkw2a
Safe Media V2: https://tinyurl.com/mrxhvej8"""


def trial_ready_text(credentials):
    return account_ready_text('<u>24 Hour Trial</u>',credentials)


def membership_ready_text(plan,credentials):
    heading='<u>Membership — '+escape(plan['name'])+'</u>'
    if plan.get('detail'): heading+='\n'+escape(plan['detail'])
    return account_ready_text(heading,credentials)


def account_ready_text(heading,credentials):
    # The heading and login details sit in one quoted box above the shared guide.
    return ('<blockquote>'+heading+'\n\n'
            '<b>Username: '+escape(credentials['username'])+'</b>\n'
            '<b>Password: '+escape(credentials['password'])+'</b></blockquote>\n\n'+APP_DOWNLOAD_GUIDE)
