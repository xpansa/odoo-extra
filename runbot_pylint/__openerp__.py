{
    'name': 'Runbot Lint',
    'description': "Runbot Pylint integration",
    'category': 'Website',
    'version': '1.0',
    'author': 'Odoo SA',
    'depends': ['runbot'],
    'data': [
        'data/runbot.xml',
        'security/ir.model.access.csv',
    ],
}
