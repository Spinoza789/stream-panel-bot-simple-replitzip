"""Customer-facing setup instructions shared by trials and memberships."""

APP_DOWNLOAD_GUIDE = """APP DOWNLOAD CODES

Enter a code in the Downloader app (Firestick):
Sky Live
2976199 • 565410 • 6261787
962396 • 969828

Magic
9801832

Safe Media
589666 • 7400092

iPhone/Apple TV App - viziplayer.com/app
URL Code BA896705

Android APPS
Sky Live: https://tinyurl.com/256zmkh3
Sky Glass: https://bit.ly/uhdglass
Smarters: https://apk.st/HVJU
Magic: https://apk.st/VPYJV
Safe Media: https://tinyurl.com/4fevkw2a
Safe Media V2: https://tinyurl.com/mrxhvej8"""


def trial_ready_text(credentials):
    return account_ready_text('24 Hour Trial',credentials)


def membership_ready_text(plan,credentials):
    heading='Membership — '+plan['name']
    if plan.get('detail'): heading+='\n'+plan['detail']
    return account_ready_text(heading,credentials)


def account_ready_text(heading,credentials):
    return (heading+'\n\n'
            'Username: '+credentials['username']+'\n'
            'Password: '+credentials['password']+'\n\n'+APP_DOWNLOAD_GUIDE)
