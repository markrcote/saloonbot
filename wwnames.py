import random


class WildWestNames:
    def __init__(self):
        self.male_names = self.load_names('M')
        self.female_names = self.load_names('F')
        self.surnames = self.load_names('S')

    def load_names(self, name_type):
        with open(f'names/{name_type}.txt') as inf:
            return [name.strip() for name in inf.readlines()]

    def random_name(self, gender=None, number=1):
        if gender:
            gender = gender.upper()[0]
            if gender not in 'MF':
                gender = None

        names = []

        for _ in range(0, number):
            cur_gender = gender
            if not cur_gender:
                cur_gender = random.choice('MF')

            first_names = self.female_names if cur_gender == 'F' else self.male_names
            gender_symbol = '♀' if cur_gender == 'F' else '♂'

            names.append(f'{gender_symbol} {random.choice(first_names)} {random.choice(self.surnames)}')

        return '\n'.join(names)
