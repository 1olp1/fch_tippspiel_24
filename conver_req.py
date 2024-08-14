def convert_requirements_txt_to_in(txt_file='requirements.txt', in_file='requirements.in'):
    with open(txt_file, 'r') as f:
        lines = f.readlines()
    
    with open(in_file, 'w') as f:
        for line in lines:
            # Remove anything after '==' or '>=', '<=', '>', '<' if present
            package = line.split('==')[0].split('>=')[0].split('<=')[0].split('>')[0].split('<')[0]
            f.write(package.strip() + '\n')

convert_requirements_txt_to_in()
