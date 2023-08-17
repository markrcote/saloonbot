import random

class WildWestNames:
    def __init__(self):
        self.male_names = self.load_names('M')
        self.female_names = self.load_names('F')
        self.surnames = self.load_names('S')

    def load_names(self, name_type):
        with open(f'names/{name_type}.txt') as inf:
            return [name.strip() for name in inf.readlines()]

    def random_name(self, gender=None):
        if gender:
            gender = gender.upper()[0]
            if gender not in 'MF':
                  gender = None

        if not gender:
            gender = random.choice('MF')

        first_names = self.female_names if gender == 'F' else self.male_names
        gender_symbol = '♀' if gender == 'F' else '♂'

        return f'{gender_symbol} {random.choice(first_names)} {random.choice(self.surnames)}'
