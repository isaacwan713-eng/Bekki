import json
import os 
from datetime import datetime,timedelta



DATA_FOLDER = 'data'

TEMPORARY_FILE = os.path.join(DATA_FOLDER,"temporary.json")
TASK_FILE = os.path.join(DATA_FOLDER,"task.json")
PROFILE_FILE=os.path.join(DATA_FOLDER,"profile.json")

def create_json_file(file_path,default_data):
    if not os.path.exists(file_path):
        with open(file_path,"w",encoding="utf-8") as file:
            json.dump(
                default_data,
                file,
                ensure_ascii= False,
                indent = 4
            )

def load_json_file(file_path):
    with open(file_path,"r",encoding='utf-8') as file:
        return json.load(file)

def save_json_file(file_path,data):
    with open(file_path,"w",encoding= "utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii= False,
            indent= 4
        )

def clean_expired_temporary(memory_data):
    current_time = datetime.now()

    valid_memories = []

    for memory in memory_data["temporary"]:
        expires_at

def initialize_memory():
    if not os.path.exists(DATA_FOLDER):
        os.mkdir(DATA_FOLDER)

    create_json_file(
        TEMPORARY_FILE,
        []
    )
    create_json_file(
        TASK_FILE,
        []
    )
    create_json_file(
        PROFILE_FILE,
        {
            "profile" :{},
            "preference" :{},
            "relationships":{}
        }
    )

    memory_data = {
    "temporary" : load_json_file(TEMPORARY_FILE),
    "tasks" : load_json_file(TASK_FILE),
    "profile" : load_json_file(PROFILE_FILE)
    }

    clean_expired_temporary(memory_data)

    return memory_data

def add_temporary(memory_data,content):
    created_at = datetime.now()
    expires_at = created_at + timedelta(hours= 24)
    new_memory = {
        "content" : content,
        "created_at" : created_at.isoformat(),
        "expires_at" : expires_at.isoformat()
    }

    memory_data["temporary"].append(new_memory)

    save_json_file(
        TEMPORARY_FILE,
        memory_data["temporary"]
        )

def clean_expired_temporary(memory_data):
    current_time = datetime.now()

    valid_memories = []

    for memory in memory_data["temporary"]:
        expires_at = datetime.fromisoformat(
            memory["expires_at"]
        )
        if expires_at > current_time:
            valid_memories.append(memory)
    memory_data["temporary"] = valid_memories

    save_json_file(
        TEMPORARY_FILE,
        memory_data["temporary"])