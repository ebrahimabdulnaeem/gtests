import html
import gradio as gr
from deep_translator import GoogleTranslator, DeeplTranslator, LibreTranslator
from extensions.google_translate_plus.lang_codes import language_codes
import json
import os
import re
import concurrent.futures
import uuid

settings_path = "extensions/google_translate_plus/settings.json"

default_params = {
    "Translate_user_input": True,
    "Translate_system_output": True,
    "language string": "ru",
    "debug": False,
    "special_symbol": "~",
    "newline_symbol": "@",
    "engine": "google",
    "LibreTranslateAPI": "http://localhost:5000/",
    "LibreTranslateAPIkey": "",
    "DeeplAPIkey": "",
    "DeeplFreeAPI": True,
    "max_length": 1500,
    "disable_split": False,
    "disable_newline_replacement": False,
    "enable_input_caching": True,
    "enable_output_caching": True,
    "translation_timeout": 10,
    "preserve_formatting": True,
    "rtl_support": True
}

try:
    if os.path.exists(settings_path):
        with open(settings_path, "r") as file:
            params = json.load(file)
        for key in default_params:
            if key not in params:
                params[key] = default_params[key]
    else:
        params = default_params.copy()
        with open(settings_path, "w") as file:
            json.dump(params, file, ensure_ascii=False, indent=4)
except json.JSONDecodeError:
    print("[Google translate plus]: Warning: settings.json has an invalid structure. Using default settings.")
    params = default_params.copy()

engines = {'Deepl Translator': 'deepl', 'Google Translate': 'google', 'LibreTranslate (local)': 'libre'}

def input_modifier(string):
    if not params.get('Translate_user_input', True):
        if params.get('debug', False):
            print("[Google translate plus]: Input text translation disabled")
        return string

    if params.get('enable_input_caching', True):
        if hasattr(input_modifier, 'previous_text') and hasattr(input_modifier, 'previous_translation'):
            if string == input_modifier.previous_text:
                if params.get('debug', False):
                    print("[Google translate plus]: Using cached translation")
                return input_modifier.previous_translation

    translated_text = translate_text(string, params.get('language string', 'ru'), "en")

    if params.get('enable_input_caching', True):
        input_modifier.previous_text = string
        input_modifier.previous_translation = translated_text

    return translated_text

def output_modifier(string):
    if not params.get('Translate_system_output', True):
        if params.get('debug', False):
            print("[Google translate plus]: Output text translation disabled")
        return string

    # Add caching for output text similar to input caching
    if params.get('enable_output_caching', True):
        if hasattr(output_modifier, 'previous_text') and hasattr(output_modifier, 'previous_translation'):
            if string == output_modifier.previous_text:
                if params.get('debug', False):
                    print("[Google translate plus]: Using cached output translation")
                return output_modifier.previous_translation

    translated_text = translate_text(string, "en", params.get('language string', 'ru'))
    
    # Store in cache
    if params.get('enable_output_caching', True):
        output_modifier.previous_text = string
        output_modifier.previous_translation = translated_text
        
    return translated_text

def translate_text(string, sourcelang, targetlang):
    """
    Main translation function that handles the translation process
    
    Args:
        string: The text to translate
        sourcelang: Source language code
        targetlang: Target language code
        
    Returns:
        Translated text or original text if translation fails
    """
    debug = params.get('debug', False)
    engine = params.get('engine', 'google')
    if debug:
        print("\n------[Google translate plus debug info]-----")
        print(f"[Google translate plus]: Using {engine.capitalize()} Translator...")

    MAX_LEN = params.get('max_length', 1500)
    special_symbol = params.get('special_symbol', '~')
    newline_symbol = params.get('newline_symbol', '@')
    disable_split = params.get('disable_split', False)
    disable_newline_replacement = params.get('disable_newline_replacement', False)
    preserve_formatting = params.get('preserve_formatting', True)
    rtl_support = params.get('rtl_support', True)
    LibreTranslateAPI = params.get('LibreTranslateAPI', "http://localhost:5000/")
    LibreTranslateAPIkey = params.get('LibreTranslateAPIkey', "")
    DeeplAPIkey = params.get('DeeplAPIkey', "")
    DeeplFreeAPI = params.get('DeeplFreeAPI', True)
    translation_timeout = params.get('translation_timeout', 10)
    
    # Check if the target language is RTL
    rtl_languages = ['ar', 'he', 'fa', 'ur', 'yi', 'ckb', 'sd', 'ug', 'ps']
    is_rtl = targetlang in rtl_languages
    
    # Check if the language is supported by the selected engine
    if engine == 'google' and targetlang not in GoogleTranslator().get_supported_languages():
        if debug:
            print(f"[Google translate plus]: Warning - Language {targetlang} may not be supported by Google Translator")
    
    if debug:
        print("[Google translate plus]: Translation parameters:")
        print(f"  Special symbol: {special_symbol}")
        print(f"  Newline symbol: {newline_symbol}")
        print(f"  Disable split: {disable_split}")
        print(f"  Disable newline replacement: {disable_newline_replacement}")
        print(f"  Preserve formatting: {preserve_formatting}")
        print(f"  RTL support: {rtl_support} (Target language is{' ' if is_rtl else ' not '}RTL)\n")
        print("[Google translate plus]: The text is currently being translated:")
        print("\033[32m" + string + "\033[0m\n")

    # Validate special_symbol and newline_symbol
    if not special_symbol:
        if debug:
            print("[Google translate plus]: Error: Special symbol cannot be empty.")
        return string
    if not newline_symbol:
        if debug:
            print("[Google translate plus]: Error: Newline symbol cannot be empty.")
        return string
        
    # Preserve formatting if enabled
    if preserve_formatting:
        string, format_placeholders = preserve_text_formatting(string, special_symbol)
        
    # Escape special_symbol in the text to avoid conflicts with the splitting pattern
    escaped_special_symbol = special_symbol + special_symbol  # Double the symbol as an escape sequence
    string = string.replace(special_symbol, escaped_special_symbol)
    
    # Now split the text using the special symbol
    fragments = re.split(f"{re.escape(special_symbol)}(.*?){re.escape(special_symbol)}", string)

    translated_fragments = []
    try:
        for idx, fragment in enumerate(fragments):
            if idx % 2 == 1:
                # Text between special symbols is not translated
                translated_fragments.append(fragment)
                continue
                
            # Restore any escaped special symbols
            fragment = fragment.replace(escaped_special_symbol, special_symbol)

            if not disable_newline_replacement:
                # Preserve newlines with a marker to ensure they're properly restored
                fragment = fragment.replace("\n", f" {newline_symbol} ")

            if disable_split or len(fragment) <= MAX_LEN:
                translated_str = translate_with_timeout(fragment, sourcelang, targetlang, engine, LibreTranslateAPI, LibreTranslateAPIkey, DeeplAPIkey, DeeplFreeAPI, translation_timeout)
                if translated_str is None:
                    if debug:
                        print("[Google translate plus]: Translation failed, returning original text")
                    gr.warning("Translation failed, returning original text")
                    return string  # Return original text if translation failed
                translated_fragments.append(translated_str)
            else:
                # Improved text splitting for long content
                parts = smart_split_text(fragment, MAX_LEN, newline_symbol)
                
                translated_parts = []
                for part in parts:
                    translated_part = translate_with_timeout(part, sourcelang, targetlang, engine, LibreTranslateAPI, LibreTranslateAPIkey, DeeplAPIkey, DeeplFreeAPI, translation_timeout)
                    if translated_part is None:
                        if debug:
                            print("[Google translate plus]: Translation failed, returning original text")
                        gr.warning("Translation failed, returning original text")
                        return string  # Return original text if translation failed
                    translated_parts.append(translated_part)
                
                translated_fragments.append(" ".join(translated_parts))

    except Exception as e:
        if debug:
            print(f"[Google translate plus]: An error occurred during translation: {e}")
        gr.warning(f"An error occurred during translation: {e}")
        return string

    translated_text = "".join(translated_fragments)

    if not disable_newline_replacement:
        # Improved newline restoration that preserves spacing
        regex_pattern = r'\s*{}\s*'.format(re.escape(newline_symbol))
        translated_text = re.sub(regex_pattern, '\n', translated_text)
    
    # Enhanced HTML entity handling
    translated_text = html.unescape(translated_text)
    
    # Restore formatting if it was preserved
    if preserve_formatting and 'format_placeholders' in locals():
        translated_text = restore_text_formatting(translated_text, format_placeholders)
        
    # Add RTL markers if needed and enabled
    if rtl_support and is_rtl:
        # Add RTL embedding controls for proper display
        translated_text = f"\u202B{translated_text}\u202C"

    if debug:
        print("[Google translate plus]: The text has been successfully translated. Result:")
        print("\033[32m" + translated_text + "\033[0m\n")
        print("---------------------------------------------")
    return translated_text

def smart_split_text(text, max_length, newline_symbol):
    """Split text intelligently at sentence or paragraph boundaries"""
    if len(text) <= max_length:
        return [text]
        
    parts = []
    while len(text) > 0:
        if len(text) <= max_length:
            parts.append(text)
            break
            
        # Try to split at paragraph (newline symbol)
        pos = text.rfind(newline_symbol, 0, max_length)
        
        if pos == -1 or pos == 0:
            # Try to split at sentence boundary
            sentence_boundaries = ['. ', '! ', '? ', '.\n', '!\n', '?\n']
            pos = -1
            for boundary in sentence_boundaries:
                boundary_pos = text.rfind(boundary, 0, max_length - len(boundary) + 2)
                if boundary_pos > pos:
                    pos = boundary_pos + len(boundary) - 1
                    
            # If no sentence boundary found, try to split at space
            if pos == -1 or pos == 0:
                pos = text.rfind(' ', 0, max_length)
                
            # If still no good split point, just split at max_length
            if pos == -1 or pos == 0:
                pos = max_length
                
        part = text[:pos+1].strip()
        text = text[pos+1:].strip()
        
        if part:
            parts.append(part)
            
    return parts

def translate_with_timeout(fragment, sourcelang, targetlang, engine, LibreTranslateAPI, LibreTranslateAPIkey, DeeplAPIkey, DeeplFreeAPI, timeout):
    debug = params.get('debug', False)
    attempt = 0
    max_attempts = 3
    while attempt < max_attempts:
        attempt += 1
        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(perform_translation, fragment, sourcelang, targetlang, engine, LibreTranslateAPI, LibreTranslateAPIkey, DeeplAPIkey, DeeplFreeAPI)
                translated_str = future.result(timeout=timeout)
                if translated_str is None:
                    if attempt < max_attempts:
                        if debug:
                            print(f"[Google translate plus]: Translation attempt {attempt} failed. Retrying...")
                        continue
                    else:
                        if debug:
                            print("[Google translate plus]: All translation attempts failed.")
                        return None
                return translated_str
        except concurrent.futures.TimeoutError:
            if attempt < max_attempts:
                if debug:
                    print(f"[Google translate plus]: Translation timed out (attempt {attempt}). Retrying...")
                gr.warning(f"Translation timed out (attempt {attempt}). Retrying...")
            else:
                if debug:
                    print("[Google translate plus]: Translation timed out after all attempts. Returning original text.")
                gr.error("Translation timed out after all attempts. Returning original text.")
                return None
        except Exception as e:
            if debug:
                print(f"[Google translate plus]: An error occurred during translation (attempt {attempt}): {e}")
            if attempt < max_attempts:
                gr.warning(f"Translation error (attempt {attempt}): {e}. Retrying...")
            else:
                gr.error(f"Translation failed after all attempts: {e}")
                return None

def perform_translation(fragment, sourcelang, targetlang, engine, LibreTranslateAPI, LibreTranslateAPIkey, DeeplAPIkey, DeeplFreeAPI):
    """
    Perform the actual translation using the selected engine
    
    Args:
        fragment: Text fragment to translate
        sourcelang: Source language code
        targetlang: Target language code
        engine: Translation engine to use
        LibreTranslateAPI: API URL for LibreTranslate
        LibreTranslateAPIkey: API key for LibreTranslate
        DeeplAPIkey: API key for DeepL
        DeeplFreeAPI: Whether to use DeepL free API
        
    Returns:
        Translated text or None if translation fails
    """
    fragment_unescaped = html.unescape(fragment)
    
    try:
        if engine == 'google':
            translated_str = str(GoogleTranslator(source=sourcelang, target=targetlang).translate(fragment_unescaped))
        elif engine == 'libre':
            translated_str = str(LibreTranslator(
                source=sourcelang,
                target=targetlang,
                base_url=LibreTranslateAPI,
                api_key=LibreTranslateAPIkey
            ).translate(fragment_unescaped))
        elif engine == 'deepl':
            translated_str = str(DeeplTranslator(
                source=sourcelang,
                target=targetlang,
                api_key=DeeplAPIkey,
                use_free_api=DeeplFreeAPI
            ).translate(fragment_unescaped))
        else:
            translated_str = fragment  # No translation
            
        return translated_str
    except Exception as e:
        print(f"[Google translate plus]: Translation error: {e}")
        return None

def bot_prefix_modifier(string):
    return string

def save_params():
    with open(settings_path, "w") as file:
        json.dump(params, file, ensure_ascii=False, indent=4)

def ui():
    # Finding the language name from the language code to use as the default value
    language_name = next((k for k, v in language_codes.items() if v == params.get('language string', 'ru')), 'English')
    engine_name = next((k for k, v in engines.items() if v == params.get('engine', 'google')), 'Google Translate')

    # Gradio elements
    with gr.Accordion("Google Translate Plus", open=False):
        with gr.Column():
            Translate_user_input = gr.Checkbox(value=params.get('Translate_user_input', True), label='Translate user input')
            Translate_system_output = gr.Checkbox(value=params.get('Translate_system_output', True), label='Translate system output')
            enable_input_caching = gr.Checkbox(value=params.get('enable_input_caching', True), label='Enable input caching',
                info='If enabled, identical input texts will use the cached translation instead of re-translating.')
            enable_output_caching = gr.Checkbox(value=params.get('enable_output_caching', True), label='Enable output caching',
                info='If enabled, identical output texts will use the cached translation instead of re-translating.')
            disable_split = gr.Checkbox(value=params.get('disable_split', False), label='Disable split',
                info='Disables splitting long text into paragraphs. May improve translation quality, but Google Translate may give an error due to too long text. This will also disable the special symbol.')
            disable_newline_replacement = gr.Checkbox(value=params.get('disable_newline_replacement', False), label='Disable newline replacement',
                info='Disables the replacement of a newline by a special character. Recommended when using LibreTranslate.')
            preserve_formatting = gr.Checkbox(value=params.get('preserve_formatting', True), label='Preserve formatting',
                info='Attempts to preserve text formatting like bold, italic, and links during translation.')
            rtl_support = gr.Checkbox(value=params.get('rtl_support', True), label='RTL language support',
                info='Adds special markers for right-to-left languages like Arabic, Hebrew, Persian, etc.')
            with gr.Accordion("Advanced", open=False):
                language = gr.Dropdown(value=language_name, choices=[k for k in language_codes], label='Language')
                engine = gr.Dropdown(value=engine_name, choices=[k for k in engines], label='Translation service')
                special_symbol = gr.Textbox(value=params.get('special_symbol', '~'), label='Special symbol.',
                    info='Text between two such syblols will not be translated. May cause inaccurate translations, and some symbols other than the standard ~ may cause errors.', type='text',
                    )
                newline_symbol = gr.Textbox(value=params.get('newline_symbol', '@'), label='Newline symbol',
                    info='Before translation, this symbol replaces the new line, and after translation it is removed. Needed to save strings after translation. Some symbols may cause errors.',
                    type='text',)
                max_length = gr.Number(value=params.get('max_length', 1500), label='Maximum text length',
                    info='If the text length exceeds this value, it will be divided into paragraphs before translation, each of which will be translated separately.',
                    precision=0)
                translation_timeout = gr.Number(value=params.get('translation_timeout', 10), label='Translation timeout (seconds)',
                    info='Maximum time to wait for translation before retrying or failing.',
                    precision=0)
                debug = gr.Checkbox(value=params.get('debug', False), label='Log translation debug info to console')
            with gr.Accordion("Translator settings", open=False):
                LibreTranslateAPI = gr.Textbox(value=params.get('LibreTranslateAPI', "http://localhost:5000/"), label='LibreTranslate API',
                    info='Your LibreTranslate address and port.',
                    type='text',)
                LibreTranslateAPIkey = gr.Textbox(value=params.get('LibreTranslateAPIkey', ""), label='LibreTranslate API key',
                    info='Your LibreTranslate API key',
                    type='text',)
                DeeplAPIkey = gr.Textbox(value=params.get('DeeplAPIkey', ""), label='Deepl API key',
                    info='Your Deepl Translator API key',
                    type='text',)
                DeeplFreeAPI = gr.Checkbox(value=params.get('DeeplFreeAPI', True), label='Use the free Deepl API')

    # Event functions to update the parameters in the backend
    Translate_user_input.change(lambda x: params.update({"Translate_user_input": x}) or save_params(), Translate_user_input, None)
    Translate_system_output.change(lambda x: params.update({"Translate_system_output": x}) or save_params(), Translate_system_output, None)
    enable_input_caching.change(lambda x: params.update({"enable_input_caching": x}) or save_params(), enable_input_caching, None)
    enable_output_caching.change(lambda x: params.update({"enable_output_caching": x}) or save_params(), enable_output_caching, None)
    disable_split.change(lambda x: params.update({"disable_split": x}) or save_params(), disable_split, None)
    disable_newline_replacement.change(lambda x: params.update({"disable_newline_replacement": x}) or save_params(), disable_newline_replacement, None)
    preserve_formatting.change(lambda x: params.update({"preserve_formatting": x}) or save_params(), preserve_formatting, None)
    rtl_support.change(lambda x: params.update({"rtl_support": x}) or save_params(), rtl_support, None)

    # Advanced settings
    def update_special_symbol(x):
        if not x:
            raise gr.Error("Special symbol cannot be empty.")
        params.update({"special_symbol": x})
        save_params()
    special_symbol.change(update_special_symbol, special_symbol, None)

    def update_newline_symbol(x):
        if not x:
            raise gr.Error("Newline symbol cannot be empty.")
        params.update({"newline_symbol": x})
        save_params()
    newline_symbol.change(update_newline_symbol, newline_symbol, None)

    language.change(lambda x: params.update({"language string": language_codes[x]}) or save_params(), language, None)
    engine.change(lambda x: params.update({"engine": engines[x]}) or save_params(), engine, None)
    max_length.change(lambda x: params.update({"max_length": int(x)}) or save_params(), max_length, None)
    translation_timeout.change(lambda x: params.update({"translation_timeout": int(x)}) or save_params(), translation_timeout, None)
    debug.change(lambda x: params.update({"debug": x}) or save_params(), debug, None)

    # Translator settings
    LibreTranslateAPI.change(lambda x: params.update({"LibreTranslateAPI": x}) or save_params(), LibreTranslateAPI, None)
    LibreTranslateAPIkey.change(lambda x: params.update({"LibreTranslateAPIkey": x}) or save_params(), LibreTranslateAPIkey, None)
    DeeplAPIkey.change(lambda x: params.update({"DeeplAPIkey": x}) or save_params(), DeeplAPIkey, None)
    DeeplFreeAPI.change(lambda x: params.update({"DeeplFreeAPI": x}) or save_params(), DeeplFreeAPI, None)

def preserve_text_formatting(text, special_symbol):
    """
    Preserve formatting elements like bold, italic, links, etc. by replacing them with placeholders
    Returns the modified text and a dictionary of placeholders to restore later
    """
    placeholders = {}
    
    # Define patterns to match common formatting
    patterns = [
        # Markdown/Discord style formatting
        (r'\*\*(.*?)\*\*', r'<b>\1</b>'),  # Bold
        (r'\*(.*?)\*', r'<i>\1</i>'),      # Italic
        (r'__(.*?)__', r'<u>\1</u>'),      # Underline
        (r'~~(.*?)~~', r'<s>\1</s>'),      # Strikethrough
        (r'```(.*?)```', r'<code>\1</code>'),  # Code block
        (r'`(.*?)`', r'<code>\1</code>'),  # Inline code
        
        # HTML style formatting (already in the text)
        (r'<b>(.*?)</b>', r'<b>\1</b>'),
        (r'<i>(.*?)</i>', r'<i>\1</i>'),
        (r'<u>(.*?)</u>', r'<u>\1</u>'),
        (r'<s>(.*?)</s>', r'<s>\1</s>'),
        (r'<code>(.*?)</code>', r'<code>\1</code>'),
        
        # Links
        (r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>'),  # Markdown links
        (r'<a\s+href=[\'"]([^\'"]*)[\'"]>(.*?)</a>', r'<a href="\1">\2</a>')  # HTML links
    ]
    
    # Process each pattern
    for pattern, replacement in patterns:
        matches = re.finditer(pattern, text, re.DOTALL)
        for match in matches:
            # Generate a unique placeholder
            placeholder_id = str(uuid.uuid4())
            placeholder = f"{special_symbol}PLACEHOLDER_{placeholder_id}{special_symbol}"
            
            # Store the original formatted text
            if '<' in replacement and '>' in replacement:
                # It's an HTML tag pattern
                content = match.group(1)
                formatted_text = replacement.replace(r'\1', content)
            else:
                # It's the original matched text
                formatted_text = match.group(0)
                
            placeholders[placeholder] = formatted_text
            
            # Replace in the text
            text = text.replace(match.group(0), placeholder, 1)
    
    return text, placeholders

def restore_text_formatting(text, placeholders):
    """
    Restore formatting elements from placeholders
    """
    for placeholder, original in placeholders.items():
        text = text.replace(placeholder, original)
    return text
