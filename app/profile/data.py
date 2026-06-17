PROFILES = [
    {
        "id": 1,
        "name": "Satin Bowerbird",
        "age": 7,
        "city": "Paris",
        "interests": ["Coffee", "Travel", "Photography", "Sunsets"],
        "bio": "I believe in love at first chirp. I collect shiny blue objects and build cozy nests on Sundays.",
        "image": "",
    },
    {
        "id": 2,
        "name": "Scarlet Macaw",
        "age": 6,
        "city": "Lyon",
        "interests": ["Music", "Hiking", "Espresso"],
        "bio": "Always up for a spontaneous trip and deep conversations over coffee.",
        "image": "",
    },
]


def get_profile_by_id(profile_id):
    return next((profile for profile in PROFILES if profile["id"] == profile_id), None)
