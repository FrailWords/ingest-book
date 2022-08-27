"""
Original Authors: Chris/Nikolai
Hookup a book to the api by looking up its VID in database using ESTC no.
Called from the workflow.
"""
from csv import DictReader
import requests
import subprocess
from .sheets.sheet import get_full_printer_name_for_short_name, update_uuid_in_sheet_for_estc_number
from .estc_search.estc import est_info_for_number

API_TOKEN_FILE_PATH = '/Users/sriram/cmu/books/api_token.txt'
JSON_OUTPUT_PATH = '/Users/sriram/cmu/books'
BOOKS_API_URL = 'http://localhost:8080/api/books/'
BOOKS_URL = 'https://printprobdb.psc.edu/books'
CERT_PATH = '/ocean/projects/hum160002p/shared/api/incommonrsaserverca-bundle.crt'
BULK_LOAD_JSON_SCRIPT = '/ocean/projects/hum160002p/shared/api/bulk_load_json.py'
VIRTUAL_ENV_PATH = '/ocean/projects/hum160002p/gsell/.conda/envs/my_env'
ESTC_LOOKUP_CSV = '/Users/sriram/cmu/books/estc_vid_lookup.csv'


def _load_token(path_to_token):
    with open(path_to_token) as f:
        token = f.read()
        token = token.rstrip()
    return token


def _build_headers(token):
    return {'Authorization': 'Token {}'.format(token)}


def _get_vid_for_estc_number(estc_number):
    with open(ESTC_LOOKUP_CSV) as csvfile:
        reader = DictReader(csvfile)
        for row in reader:
            # check the arguments against the row
            if row['estcNO'] == estc_number:
                return dict(row).get('VID')


def _get_vid(estc_number_as_string) -> str:
    try:
        vid = _get_vid_for_estc_number(estc_number=estc_number_as_string)
        return vid
    except IndexError:
        print("It looks like that ESTC number may not be in our file?")


def _retrieve_metadata(vid, verify, headers):
    payload = {'vid': vid}
    r = requests.get(BOOKS_API_URL, headers=headers, params=payload, verify=verify)
    return r.json()


def _api_headers():
    token = _load_token(API_TOKEN_FILE_PATH)
    headers = _build_headers(token)
    return headers


def _create_book(book, printer):
    payload = {
        # "id": None,
        "eebo": book['eebo'],
        "vid": book['vid'],
        "tcp": book['tcp'],
        "estc": book['estc'],
        "zipfile": "",
        "pp_publisher": book['pp_publisher'],
        "pp_author": book['pp_author'],
        "pq_publisher": book['pq_publisher'],
        "pq_title": book['pq_title'],
        "pq_url": book['pq_url'],
        "pq_author": book['pq_author'],
        "pq_year_verbatim": book['pq_year_verbatim'],
        "pq_year_early": book['pq_year_early'],
        "pq_year_late": book['pq_year_late'],
        "tx_year_early": book['tx_year_early'],
        "tx_year_late": book['tx_year_late'],
        "date_early": book['date_early'],
        "date_late": book['date_late'],
        "pdf": "",
        "starred": False,
        "ignored": False,
        "is_eebo_book": False,
        "prefix": None,
        "repository": "",
        "pp_printer": printer,
        "colloq_printer": "",
        "pp_notes": ""
    }
    # print(payload)
    r = requests.post(BOOKS_API_URL, headers=_api_headers(), json=payload, verify=None)
    return r.json()


def _get_uuid_and_post_new_data(vid, printer=None):
    book_metadata = _retrieve_metadata(vid, CERT_PATH, _api_headers())
    if bool(book_metadata['results']):
        book = book_metadata['results'][0]
        response = _create_book(book, printer)
        return response['id']
    else:
        print('Error fetching metadata for VID -', vid)


# Create the batch command to ingest the book
def _create_bash_command(book_uuid, folder_name):
    batch_command_prefix = 'sbatch -c 4 --mem-per-cpu=1999mb -p "RM-shared" -t 48:00:00'
    activate_virtual_env = 'source activate {0}'.format(VIRTUAL_ENV_PATH)
    command_to_run = 'python3 {BULK_LOAD_JSON_SCRIPT} -b {book_uuid} -j {JSON_OUTPUT_PATH}/{folder_name}'.format(
        BULK_LOAD_JSON_SCRIPT=BULK_LOAD_JSON_SCRIPT, book_uuid=book_uuid,
        JSON_OUTPUT_PATH=JSON_OUTPUT_PATH, folder_name=folder_name)
    return '{batch_command_prefix} --wrap="module load anaconda3; {activate_virtual_env}; {command_to_run}"' \
        .format(batch_command_prefix=batch_command_prefix,
                activate_virtual_env=activate_virtual_env,
                command_to_run=command_to_run)


# Lookup printer full name from the Google sheet 'Printers' worksheet
def _get_printer_name_from_sheet(printer_short_name):
    get_full_printer_name_for_short_name(printer_short_name)


def run_command(book_string, preexisting_uuid, printer):
    # Folder name is same as the book string
    folder_name = book_string

    split_book_string = book_string.split('_')

    # ESTC number is the second element in the split book string
    estc_no = split_book_string[1]
    print("ESTC number - ", estc_no)

    # Use printer passed as argument, default to the fullname from Google sheet or the short-name as last default
    book_printer = printer if printer is not None else _get_printer_name_from_sheet(split_book_string[0])
    print("Using printer name as - ", book_printer)

    # if this book already exists in our backend
    if preexisting_uuid is not None:
        print("Pre-existing UUID provided: ", preexisting_uuid)
        command = _create_bash_command(preexisting_uuid, folder_name)
    else: # this is a new book, we need to create it first
        vid = _get_vid(estc_no)
        uuid = _get_uuid_and_post_new_data(vid, book_printer)

        # Update the book UUID in the Google sheet
        print("BOOK CREATED", uuid)
        print("Updating UUID in Google sheet for ESTC number", estc_no, uuid)
        update_uuid_in_sheet_for_estc_number(estc_no, uuid)

        command = _create_bash_command(uuid, folder_name)

        print("ONCE COMPLETED, THIS BOOK WILL BE LOADED AT {BOOKS_URL}/{book_uuid}".format(BOOKS_URL=BOOKS_URL,
                                                                                           book_uuid=uuid))

    # subprocess.run(input=command)
    subprocess.run(command, shell=True)
    print("Job Launched")