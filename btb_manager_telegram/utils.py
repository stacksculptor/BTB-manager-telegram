import json
import os
import subprocess
from time import sleep
from typing import List, Optional

import psutil
import telegram
import yaml
from telegram import Bot
from telegram.utils.helpers import escape_markdown

import i18n
from btb_manager_telegram import logger, scheduler, settings


def setup_i18n(lang):
    i18n.set("locale", lang)
    i18n.set("fallback", "en")
    i18n.set("skip_locale_root_data", True)
    i18n.set("filename_format", "{locale}.{format}")
    i18n.load_path.append("./i18n")


def format_float(num):
    return f"{num:0.8f}".rstrip("0").rstrip(".")


def i18n_format(key, **kwargs):
    for k, val in kwargs.items():
        try:
            float(val)
            val = format_float(val)
        except:
            pass
        kwargs[k] = escape_markdown(str(val), version=2)
    return i18n.t(key, **kwargs)


def escape_tg(message):
    escape_char = (".", "-", "?", "!", ">")
    escaped_message = ""
    is_escaped = False
    for cur_char in message:
        if cur_char in escape_char and not is_escaped:
            escaped_message += "\\"
        escaped_message += cur_char
        is_escaped = cur_char == "\\" and not is_escaped
    return escaped_message


def reply_text_escape(reply_text_fun):
    def reply_text_escape_fun(message, **kwargs):
        return reply_text_fun(escape_tg(message), **kwargs)

    return reply_text_escape_fun


def setup_root_path_constant():
    if settings.ROOT_PATH is None:
        logger.info("No root_path was specified. Aborting.")
        exit(-1)
    else:
        settings.ROOT_PATH = os.path.join(settings.ROOT_PATH, "")


def setup_telegram_constants():
    logger.info("Retrieving Telegram token and chat_id from apprise.yml file.")
    telegram_url = None
    yaml_file_path = os.path.join(settings.ROOT_PATH, "config/apprise.yml")
    if os.path.exists(yaml_file_path):
        with open(yaml_file_path) as f:
            try:
                parsed_urls = yaml.load(f, Loader=yaml.FullLoader)["urls"]
            except Exception:
                logger.error(
                    "Unable to correctly read apprise.yml file. Make sure it is correctly set up. Aborting."
                )
                exit(-1)
            for url in parsed_urls:
                if url.startswith("tgram"):
                    telegram_url = url.split("//")[1]
        if not telegram_url:
            logger.error(
                "No telegram configuration was found in your apprise.yml file. Aborting."
            )
            exit(-1)
    else:
        logger.error(
            f'Unable to find apprise.yml file at "{yaml_file_path}". Aborting.'
        )
        exit(-1)
    try:
        settings.TOKEN = telegram_url.split("/")[0]
        settings.CHAT_ID = telegram_url.split("/")[1]
        logger.info(
            f"Successfully retrieved Telegram configuration. "
            f"The bot will only respond to user in the chat with chat_id {settings.CHAT_ID}"
        )
    except Exception:
        logger.error(
            "No chat_id has been set in the yaml configuration, anyone would be able to control your bot. Aborting."
        )
        exit(-1)


def telegram_text_truncator(
    m_list, padding_chars_head="", padding_chars_tail=""
) -> List[str]:
    message = [padding_chars_head]
    index = 0
    for mes in m_list:
        if (
            len(message[index]) + len(mes) + len(padding_chars_tail)
            <= telegram.constants.MAX_MESSAGE_LENGTH
        ):
            message[index] += mes
        else:
            message[index] += padding_chars_tail
            message.append(padding_chars_head + mes)
            index += 1
    message[index] += padding_chars_tail
    return message


def get_binance_trade_bot_process() -> Optional[psutil.Process]:
    name = "binance_trade_bot"
    is_root_path_absolute = os.path.isabs(settings.ROOT_PATH)
    bot_path = os.path.normpath(settings.ROOT_PATH)
    if not is_root_path_absolute:
        bot_path = os.path.normpath(os.path.join(os.getcwd(), settings.ROOT_PATH))

    for proc in psutil.process_iter():
        try:
            if (
                name in proc.name() or name in " ".join(proc.cmdline())
            ) and proc.cwd() == bot_path:
                return proc
        except psutil.AccessDenied:
            continue
        except psutil.ZombieProcess:
            continue


def find_and_kill_binance_trade_bot_process():
    try:
        binance_trade_bot_process = get_binance_trade_bot_process()
        binance_trade_bot_process.terminate()
        binance_trade_bot_process.wait()
    except Exception as e:
        logger.info(f"ERROR: {e}")


def kill_btb_manager_telegram_process():
    try:
        btb_manager_telegram_pid = os.getpid()
        btb_manager_telegram_process = psutil.Process(btb_manager_telegram_pid)
        btb_manager_telegram_process.kill()
        btb_manager_telegram_process.wait()
    except Exception as e:
        logger.info(f"ERROR: {e}")


def is_tg_bot_update_available():
    try:
        proc = subprocess.Popen(
            ["bash", "-c", "git remote update && git status -uno"],
            stdout=subprocess.PIPE,
        )
        output, _ = proc.communicate()
        re = "Your branch is behind" in str(output)
    except Exception as e:
        logger.error(e, exc_info=True)
        re = None
    return re


def is_btb_bot_update_available():
    try:
        proc = subprocess.Popen(
            [
                "bash",
                "-c",
                f"cd {settings.ROOT_PATH} && git remote update && git status -uno",
            ],
            stdout=subprocess.PIPE,
        )
        output, _ = proc.communicate()
        re = "Your branch is behind" in str(output)
    except Exception as e:
        logger.error(e, exc_info=True)
        re = None
    return re


def update_checker():
    logger.info("Checking for updates.")

    if settings.TG_UPDATE_BROADCASTED_BEFORE is False:
        if is_tg_bot_update_available():
            logger.info("BTB Manager Telegram update found.")

            message = (
                f"{i18n_format('tg_bot_update_availabe')}\n\n"
                f"{i18n_format('tg_bot_update_instruction')}"
            )
            settings.TG_UPDATE_BROADCASTED_BEFORE = True
            settings.CHAT.send_message(
                escape_tg(message), parse_mode="MarkdownV2"
            )
            scheduler.enter(
                60 * 60 * 12,
                1,
                update_reminder,
                ("_*Reminder*_:\n\n" + message,),
            )

    if settings.BTB_UPDATE_BROADCASTED_BEFORE is False:
        if is_btb_bot_update_available():
            logger.info("Binance Trade Bot update found.")

            message = (
                f"{i18n_format('btb_update_availabe')}\n\n"
                f"{i18n_format('btb_bot_update_instruction')}"
            )
            settings.BTB_UPDATE_BROADCASTED_BEFORE = True
            settings.CHAT.send_message(
                escape_tg(message), parse_mode="MarkdownV2"
            )
            sleep(1)
            bot.close()
            sleep(1)
            scheduler.enter(
                60 * 60 * 12,
                1,
                update_reminder,
                ("_*Reminder*_:\n\n" + message,),
            )

    if (
        settings.TG_UPDATE_BROADCASTED_BEFORE is False
        or settings.BTB_UPDATE_BROADCASTED_BEFORE is False
    ):
        sleep(1)
        scheduler.enter(
            60 * 60,
            1,
            update_checker,
        )


def update_reminder(self, message):
    logger.info(f"Reminding user: {message}")

    settings.CHAT.send_message(escape_tg(message), parse_mode="MarkdownV2")
    scheduler.enter(
        60 * 60 * 12,
        1,
        update_reminder,
    )


def get_custom_scripts_keyboard():
    logger.info("Getting list of custom scripts.")

    custom_scripts_path = "./config/custom_scripts.json"
    keyboard = []
    custom_script_exist = False
    message = i18n_format("script_not_found_in_file_error")

    if os.path.exists(custom_scripts_path):
        with open(custom_scripts_path) as f:
            scripts = json.load(f)
            for script_name in scripts:
                keyboard.append([script_name])

        if len(keyboard) >= 1:
            custom_script_exist = True
            message = i18n_format("select_script")
    else:
        logger.warning(
            "Unable to find custom_scripts.json file inside BTB-manager-telegram's config/ directory."
        )
        message = i18n_format("script_not_found_in_folder_error")

    keyboard.append([i18n_format("cancel")])
    return keyboard, custom_script_exist, message
