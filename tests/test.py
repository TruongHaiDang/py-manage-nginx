from py_manage_nginx.manager import list_sites


if __name__ == '__main__':
    print(list_sites(root="/etc/nginx", directory="sites-enabled"))
