"""Customer-facing setup instructions shared by trials and memberships.

Every builder here returns Telegram HTML (parse_mode='HTML'); dynamic values are escaped."""
from html import escape

APP_GUIDE = {
    # Pictures are real screenshots: Fire TV ones from AFTVnews (the Downloader developer), app ones from the App Store listings.
    'firestick': {
        'title': 'Amazon Fire Stick / Fire TV',
        'icon': 'img/downloader-play-icon.png',
        'steps': [
            {'text': 'On the Fire TV home screen choose Find, then Search, type Downloader and install the orange Downloader app.', 'picture': 'img/fire-listing.jpg'},
            {'text': 'Open Settings, My Fire TV, About, and click the device name seven times until it says you are a developer.', 'picture': 'img/fire-devmode.jpg'},
            {'text': 'Go back to My Fire TV, open Developer options, then Install unknown apps, and switch Downloader ON.', 'picture': 'img/fire-unknown.jpg'},
            {'text': 'Open Downloader, type one of the codes below into the URL box and press Go.', 'picture': 'img/fire-url.png'},
            {'text': 'Choose Install when the app asks, then Open.', 'picture': 'img/fire-install.png'},
            {'text': 'Log in with the username and password you were given.'},
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
        'icon': 'img/vizi-icon.jpg',
        'site': 'viziplayer.com/app',
        'url_code': 'BA896705',
        'steps': [
            {'text': 'Install Vizi Player from the App Store (open viziplayer.com/app on the device and it takes you there). On Apple TV search the App Store for Vizi Player.', 'picture': 'img/vizi-shot-1.jpg'},
            {'text': 'Open the app and choose Add Playlist. In the box labelled "Playlist URL, or LinkACode.com ID" type the URL code below.'},
            {'text': 'Enter the username and password you were given. The playlist loads and Live TV, films and series appear.', 'picture': 'img/vizi-shot-2.jpg'},
        ],
    },
    'android': {
        'title': 'Android phones, tablets & TV boxes',
        'icon': 'img/smarters-icon.jpg',
        'steps': [
            {'text': 'Open one of the links below on the device and download the APK file.'},
            {'text': 'If Android asks, allow installs from this source (Settings, Apps, Special access, Install unknown apps).'},
            {'text': 'Open the downloaded file, choose Install, then open the app and log in with the username and password you were given.'},
            {'text': 'Android TV boxes can also install Downloader from Google Play and use the Fire Stick codes above.', 'picture': 'img/fire-url.png'},
        ],
        'apps': [
            {'name': 'Sky Live', 'url': 'https://tinyurl.com/256zmkh3'},
            {'name': 'Sky Glass', 'url': 'https://bit.ly/uhdglass'},
            {'name': 'Smarters', 'url': 'https://apk.st/HVJU', 'icon': 'img/smarters-icon.jpg'},
            {'name': 'Magic', 'url': 'https://apk.st/VPYJV'},
            {'name': 'Safe Media', 'url': 'https://tinyurl.com/4fevkw2a'},
            {'name': 'Safe Media V2', 'url': 'https://tinyurl.com/mrxhvej8'},
        ],
    },
    'credits': 'Screenshots: AFTVnews (Downloader) and the App Store listings.',
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


WATCH_DEVICES = (('firestick', '🔥 Fire Stick / Fire TV'), ('apple', '🍏 iPhone, iPad, Apple TV'), ('android', '🤖 Android phone, tablet, TV box'))


def watch_menu_text():
    return ('<b>📲 HOW TO WATCH</b>\n\nSetting up takes about five minutes: install the app for your device, '
            'then sign in with the username and password from your trial or subscription.\n\nWhich device are you using?')


def watch_text(device):
    """Step-by-step setup for one device family, with its app codes or links."""
    guide = APP_GUIDE.get(device) if device in dict(WATCH_DEVICES) else None
    if not guide: return None
    lines = ['<b>📲 ' + escape(guide['title']) + '</b>', '']
    lines += [str(n) + '. ' + escape(step['text']) for n, step in enumerate(guide['steps'], 1)]
    if device == 'firestick':
        lines += ['', '<b>Downloader codes</b> (tap a code to copy it)']
        for app in guide['apps']:
            lines.append('<b>' + escape(app['name']) + '</b>: ' + ' • '.join('<code>' + escape(c) + '</code>' for c in app['codes']))
        lines += ['', escape(guide['note'])]
    elif device == 'apple':
        lines += ['', 'App: ' + escape(guide['site']), 'URL code: <code>' + escape(guide['url_code']) + '</code>']
    else:
        lines += ['', '<b>App links</b>'] + [escape(app['name']) + ': ' + escape(app['url']) for app in guide['apps']]
    lines += ['', '🔑 Need your username and password? Tap Show my login.']
    return '\n'.join(lines)
