"""Customer-facing setup instructions shared by trials and memberships.

Every builder here returns Telegram HTML (parse_mode='HTML'); dynamic values are escaped."""
from html import escape

APP_GUIDE = {
    'firestick': {
        'title': 'Amazon Fire Stick / Fire TV',
        'steps': [
            'On the Fire TV home screen choose Find, then Search, and type Downloader. Install the orange Downloader app.',
            'Go to Settings, My Fire TV, Developer options, Install unknown apps, and switch Downloader on. (If Developer options is missing, open Settings, My Fire TV, About and click the Fire TV Stick name seven times.)',
            'Open Downloader, type one of the codes below into the URL box and press Go. Install the app when asked.',
            'Open the app and log in with the username and password you were given.',
        ],
        'apps': [
            {'name': 'Sky Live', 'codes': ['2976199', '565410', '6261787', '962396', '969828']},
            {'name': 'Magic', 'codes': ['9801832']},
            {'name': 'Safe Media', 'codes': ['589666', '7400092']},
        ],
        'note': 'Any one code is enough. If a code does not work, try the next one for the same app.',
    },
    'apple': {
        'title': 'iPhone, iPad & Apple TV',
        'site': 'viziplayer.com/app',
        'url_code': 'BA896705',
        'steps': [
            'On the device open viziplayer.com/app in Safari (or the App Store link it shows) and install the player.',
            'Open the player and choose to add a playlist by URL code.',
            'Enter the URL code below, then the username and password you were given.',
            'On Apple TV, install the same app from the App Store and sign in the same way.',
        ],
    },
    'android': {
        'title': 'Android phones, tablets & TV boxes',
        'steps': [
            'Open one of the links below on the device and download the APK.',
            'If Android asks, allow installs from this source (Settings, Apps, Special access, Install unknown apps).',
            'Open the downloaded file to install, then open the app.',
            'Log in with the username and password you were given.',
        ],
        'apps': [
            {'name': 'Sky Live', 'url': 'https://tinyurl.com/256zmkh3'},
            {'name': 'Sky Glass', 'url': 'https://bit.ly/uhdglass'},
            {'name': 'Smarters', 'url': 'https://apk.st/HVJU'},
            {'name': 'Magic', 'url': 'https://apk.st/VPYJV'},
            {'name': 'Safe Media', 'url': 'https://tinyurl.com/4fevkw2a'},
            {'name': 'Safe Media V2', 'url': 'https://tinyurl.com/mrxhvej8'},
        ],
    },
}


def _telegram_guide():
    fire = APP_GUIDE['firestick']
    lines = ['<b>APP DOWNLOAD CODES</b>', '', 'Enter a code in the Downloader app (Firestick):']
    for app in fire['apps']:
        lines.append('<b>' + escape(app['name']) + '</b>')
        codes = ['<code>' + escape(c) + '</code>' for c in app['codes']]
        for i in range(0, len(codes), 3):
            lines.append(' • '.join(codes[i:i + 3]))
        lines.append('')
    apple = APP_GUIDE['apple']
    lines += ['<b>iPhone/Apple TV App</b> - ' + escape(apple['site']), 'URL Code <code>' + escape(apple['url_code']) + '</code>', '', '<b>Android APPS</b>']
    lines += [escape(app['name']) + ': ' + escape(app['url']) for app in APP_GUIDE['android']['apps']]
    return '\n'.join(lines)


APP_DOWNLOAD_GUIDE = _telegram_guide()


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
