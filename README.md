Ragnarok is both a bancho and /web/ server, written in python3.12!

Ragnarok will provide more stablibilty:tm: and way faster performance than Ripple's bancho emulator (Second login takes about 4-5ms).

Note: Ragnarok does not work on windows.

## Setup
We will not help setting up the whole server (nginx, mysql and those stuff), but just the bancho.

We suggest making an environment before doing anything. You can create one by installing pipenv.
```
$ python3.12 -m pip install pipenv
...

$ python3.12 -m pipenv install
Creating a virtualenv for this project...
...

$ pipenv shell
```

After that you can install the needed packages.
```
$ pipenv install
```

Once that's finished, you can go ahead and make a copy of the .env.example, by doing:
```
$ mv .env.example .env
$ nano .env
```

Then you can go ahead and add or change the needed stuff in there.

And the last thing you have to do, is running the server.
```
$ python server.py
```

If there's any issues during setup, feel free to post an issue.

## Requirements
Experience developing in Python.

## License
Ragnarok's code is licensed under the [GNU Affero General Public License v3 licence](https://tldrlegal.com/license/gnu-affero-general-public-license-v3-(agpl-3.0)). Please see [the licence file](https://github.com/osumitsuha/Ragnarok/blob/main/LICENSE) for more information.
