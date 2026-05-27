import os, sys

sys.path.insert(0, r'C:\Users\aman9\Downloads\MG-Techno-Pro\Management-tool\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
os.environ['DATABASE_URL'] = 'postgresql://neondb_owner:npg_kO1bPACFMEL2@ep-divine-water-apoz3ytr-pooler.c-7.us-east-1.aws.neon.tech/neondb?sslmode=require'

import django
django.setup()

from api.models import Employee
print(f'Employees: {list(Employee.objects.values_list("email", flat=True))}')
