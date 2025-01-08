#include<stdio.h>
#include<stdlib.h>
int main()
{
    int v=0;//no.of variables
    FILE *fp;
    fp=fopen("b.txt","r");
    char ch;
    int count=1;
    while(!feof(fp))
    {
        ch=fgetc(fp);
        if(ch=='\n')
        {
            count+=1;
        }
        v+=1;
    }
    /*
    while((ch=fgetc(fp))!=EOF)
    {
    if(ch=='\n')
        count++;
    }
    */
    printf("%d",count);
    printf("\n%d",v-count);
    return 0;
}